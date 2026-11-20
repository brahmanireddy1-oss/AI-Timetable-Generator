import os
import sys
import io
import pytest
import pandas as pd

# Ensure root directory is on python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from database import DatabaseManager
from timetable_generator import TimetableOptimizer
from utils import (
    ConflictValidator,
    build_timetable_grid,
    compare_timetable_versions,
    export_timetable_pdf,
    export_timetable_excel,
    export_timetable_txt
)

@pytest.fixture(scope="module")
def db():
    # Use a test database
    test_db_path = "data/test_timetable.db"
    if os.path.exists(test_db_path):
        os.remove(test_db_path)
    db_mgr = DatabaseManager(db_path=test_db_path)
    # Import demo data
    excel_path = "data/AI_Timetable_Demo_Data.xlsx"
    is_valid, errs, dfs = db_mgr.validate_excel_workbook(excel_path)
    assert is_valid, f"Demo workbook invalid: {errs}"
    ok, msg = db_mgr.import_validated_data(dfs)
    assert ok, f"Import failed: {msg}"
    yield db_mgr
    # Teardown
    if os.path.exists(test_db_path):
        try:
            os.remove(test_db_path)
        except Exception:
            pass

def test_workbook_reading_and_validation(db):
    """Test reading and validating all 9 sheets from Excel."""
    excel_path = "data/AI_Timetable_Demo_Data.xlsx"
    is_valid, errs, dfs = db.validate_excel_workbook(excel_path)
    assert is_valid is True
    assert len(errs) == 0
    assert len(dfs) == 9
    assert "Departments" in dfs
    assert "Courses" in dfs
    assert "Faculty" in dfs
    assert "Classrooms" in dfs
    assert "Students" in dfs
    assert "Time_Slots" in dfs
    assert "Faculty_Availability" in dfs
    assert "Student_Enrollments" in dfs
    assert "Constraints" in dfs

def test_database_counts(db):
    """Test that all records exist in database after import."""
    depts = db.get_departments()
    courses = db.get_courses()
    faculty = db.get_faculty()
    students = db.get_students()
    rooms = db.get_classrooms()
    slots = db.get_time_slots()

    assert len(depts) == 3
    assert len(courses) == 18
    assert len(faculty) == 12
    assert len(students) == 60
    assert len(rooms) == 10
    assert len(slots) == 30

def test_reference_integrity(db):
    """Test that deleting a referenced department is blocked."""
    ok, msg = db.delete_department("CSE")
    assert ok is False
    assert "Cannot delete department" in msg

def test_constraint_configuration(db):
    """Test reading and updating constraints."""
    constraints = db.get_constraints()
    assert not constraints.empty
    ok, msg = db.update_constraint_value("solver_time_limit_seconds", "20")
    assert ok is True
    c_updated = db.get_constraints()
    val = c_updated[c_updated["constraint_name"] == "solver_time_limit_seconds"]["constraint_value"].values[0]
    assert val == "20"
    # Restore adequate solver limit for subsequent optimization tests
    db.update_constraint_value("solver_time_limit_seconds", "60")

def test_timetable_generation_cpsat(db):
    """Test timetable optimization using Google OR-Tools CP-SAT."""
    optimizer = TimetableOptimizer(db)
    res = optimizer.generate()
    assert res["success"] is True
    assert res["status"] in ("OPTIMAL", "FEASIBLE")
    assert len(res["entries"]) == 44
    assert res["metrics"]["unscheduled_sessions"] == 0

    # Save as V1.0
    ok, msg = db.save_timetable_version(
        version_id="V1.0",
        version_name="Initial NEP Timetable",
        entries=res["entries"],
        metrics=res["metrics"],
        notes="Automated test generation"
    )
    assert ok is True

def test_independent_conflict_validation(db):
    """Test that independent validator audits V1.0 and finds zero hard clashes."""
    validator = ConflictValidator(db)
    audit = validator.validate("V1.0")
    assert audit["is_valid"] is True
    assert audit["hard_conflicts"] == 0
    assert audit["score"] == 100

def test_synthetic_faculty_clash_detection(db):
    """Test validator detection when a faculty clash is artificially introduced."""
    entries_df = db.get_timetable_entries("V1.0")
    assert not entries_df.empty
    # Duplicate an entry into same slot with different session
    clash_entries = entries_df.to_dict(orient="records")
    fake_entry = dict(clash_entries[0])
    fake_entry["session_id"] = "SYNTHETIC_CLASH_S1"
    fake_entry["course_id"] = "C102"
    clash_entries.append(fake_entry)

    db.save_timetable_version(
        version_id="V_CLASH_TEST",
        version_name="Clash Test",
        entries=clash_entries,
        metrics={},
        notes="Testing clash detection"
    )

    validator = ConflictValidator(db)
    audit = validator.validate("V_CLASH_TEST")
    assert audit["hard_conflicts"] > 0
    types = [c["type"] for c in audit["conflicts"]]
    assert "Faculty Clash" in types or "Classroom Clash" in types

def test_dynamic_regeneration_and_comparison(db):
    """Test changing faculty availability and generating a new version V2.0."""
    # Mark F001 unavailable for Friday P5
    ok, msg = db.set_faculty_availability("F001", "Friday", "P5", 0)
    assert ok is True

    optimizer = TimetableOptimizer(db)
    res = optimizer.generate()
    assert res["success"] is True

    # Save as V2.0
    db.save_timetable_version(
        version_id="V2.0",
        version_name="Regenerated Post Availability Change",
        entries=res["entries"],
        metrics=res["metrics"],
        notes="Regenerated with F001 Friday P5 unavailable"
    )

    # Compare V1.0 and V2.0
    v1_entries = db.get_timetable_entries("V1.0")
    v2_entries = db.get_timetable_entries("V2.0")
    comparison = compare_timetable_versions(v1_entries, v2_entries)

    assert comparison["total_sessions"] == 44
    assert "similarity_percentage" in comparison
    assert isinstance(comparison["differences"], list)

def test_approval_and_publishing_workflow(db):
    """Test approval workflow rules: Draft -> Approved -> Published."""
    # Attempt to publish Draft directly (should fail)
    ok, msg = db.update_version_status("V1.0", "Published", "Admin User", "Premature publish")
    assert ok is False
    assert "must be 'Approved' first" in msg

    # Approve first
    ok, msg = db.update_version_status("V1.0", "Approved", "HOD", "Approved after review")
    assert ok is True

    # Now publish
    ok, msg = db.update_version_status("V1.0", "Published", "Principal", "Published for semester")
    assert ok is True

    # Verify status in versions table
    versions = db.get_timetable_versions()
    v1_status = versions[versions["version_id"] == "V1.0"]["status"].values[0]
    assert v1_status == "Published"

    # Verify audit trail
    approvals = db.get_approval_records("V1.0")
    assert len(approvals) >= 2

def test_export_formats(db):
    """Test generating PDF, Excel, and TXT export deliverables."""
    entries_df = db.get_timetable_entries("V1.0")
    grid = build_timetable_grid(entries_df, "Department", "CSE")
    metrics = {"scheduled_sessions": len(entries_df), "conflict_count": 0, "solver_status": "OPTIMAL"}

    # 1. PDF
    pdf_bytes = export_timetable_pdf("V1.0", "NEP Timetable V1.0", "CSE Department View", grid, metrics)
    assert len(pdf_bytes.getvalue()) > 1000

    # 2. Excel
    excel_bytes = export_timetable_excel("V1.0", "NEP Timetable V1.0", "CSE Department View", entries_df, grid, metrics)
    assert len(excel_bytes.getvalue()) > 3000

    # 3. TXT
    txt_content = export_timetable_txt("V1.0", "NEP Timetable V1.0", "CSE Department View", grid, metrics)
    assert len(txt_content) > 500
    assert "NATIONAL EDUCATION POLICY" in txt_content

def test_csv_dataset_validation_and_import(db):
    """Test validating and importing the multi-table CSV format."""
    csv_file = "data/sample_dataset.csv"
    assert os.path.exists(csv_file)
    is_valid, errors, dfs = db.validate_csv_dataset(csv_file)
    assert is_valid is True
    assert len(errors) == 0
    assert len(dfs) == 9
    assert "Departments" in dfs
    assert "Students" in dfs
    assert "Courses" in dfs
    assert "Faculty" in dfs
    assert "Classrooms" in dfs
    assert "Faculty_Availability" in dfs
    assert "Student_Enrollments" in dfs
    assert "Time_Slots" in dfs
    assert "Constraints" in dfs

    # Test unified validate_uploaded_dataset
    with open(csv_file, "r", encoding="utf-8") as f:
        is_v_up, errs_up, dfs_up = db.validate_uploaded_dataset(f, filename="AI_Timetable_Sample_Dataset.csv")
    assert is_v_up is True
    assert len(errs_up) == 0
    assert len(dfs_up) == 9
