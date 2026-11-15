import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
import pandas as pd
from database import DatabaseManager
from timetable_generator import TimetableOptimizer, parse_natural_language_adjustment
from utils import ConflictValidator, build_department_cohort_grid, build_timetable_grid

@pytest.fixture(scope="module")
def setup_optimizer():
    db = DatabaseManager("data/timetable.db")
    opt = TimetableOptimizer(db)
    v_df = db.get_timetable_versions()
    if v_df.empty:
        # Generate initial if not present
        res = opt.generate()
        assert res["success"] is True
        db.save_timetable_version("V_TEST_INIT", "Initial Test", res["entries"], res["metrics"])
        active_vid = "V_TEST_INIT"
    else:
        active_vid = v_df.iloc[0]["version_id"]
    entries = db.get_timetable_entries(active_vid).to_dict(orient="records")
    return db, opt, entries

def test_nlp_parser(setup_optimizer):
    db, _, _ = setup_optimizer
    courses_df = db.get_courses()
    fac_df = db.get_faculty()
    rooms_df = db.get_classrooms()

    # 1. Move AI Lab / C104 to Friday afternoon
    r1 = parse_natural_language_adjustment("Move AI Lab to Friday afternoon", courses_df, fac_df, rooms_df)
    assert r1["parsed"] is True
    assert r1["day"] == "Friday"
    assert r1["periods"] == ["P5", "P6"]
    assert "C104" in r1["course_id"] or "C106" in r1["course_id"]

    # 2. Avoid back to back lectures
    r2 = parse_natural_language_adjustment("Avoid back-to-back lectures for Batch A", courses_df, fac_df, rooms_df)
    assert r2["parsed"] is True
    assert r2["rule_type"] == "avoid_consecutive"

    # 3. Faculty unavailable
    r3 = parse_natural_language_adjustment("Dr. Ananya Rao is unavailable on Thursday afternoon", courses_df, fac_df, rooms_df)
    assert r3["parsed"] is True
    assert r3["faculty_id"] is not None or "Thursday" in str(r3["day"])

def test_locking_and_partial_regeneration(setup_optimizer):
    db, opt, entries = setup_optimizer
    assert len(entries) > 0

    # Pick 1 session to relocate by marking its faculty unavailable
    target_entry = entries[0]
    target_fid = target_entry["faculty_id"]
    target_day = target_entry["day"]
    target_per = target_entry["period_id"]

    # Lock all other sessions
    locked_sids = {e["session_id"] for e in entries if e["session_id"] != target_entry["session_id"]}

    # Faculty disruption
    f_disruptions = [{"faculty_id": target_fid, "day": target_day, "period_id": target_per}]

    res = opt.regenerate_partial(
        current_entries=entries,
        locked_sessions=locked_sids,
        faculty_disruptions=f_disruptions
    )

    assert res["success"] is True
    new_entries = res["entries"]
    assert len(new_entries) == len(entries)

    # Verify locked sessions did NOT move
    new_map = {e["session_id"]: e for e in new_entries}
    for sid in locked_sids:
        old_e = next(e for e in entries if e["session_id"] == sid)
        new_e = new_map[sid]
        assert old_e["day"] == new_e["day"]
        assert old_e["period_id"] == new_e["period_id"]
        assert old_e["classroom_id"] == new_e["classroom_id"]

    # Verify target session did move
    moved = res["moved_sessions"]
    assert len(moved) >= 1
    target_moved = [m for m in moved if m["session_id"] == target_entry["session_id"]]
    assert len(target_moved) == 1
    assert target_moved[0]["new_slot"] != f"{target_day} {target_per}"

def test_zero_clashes_after_regeneration(setup_optimizer):
    db, opt, entries = setup_optimizer

    # Test disruption with room blocked
    locked_sids = {e["session_id"] for e in entries[5:]}
    r_dis = [{"classroom_id": entries[0]["classroom_id"], "day": entries[0]["day"], "period_id": entries[0]["period_id"]}]

    res = opt.regenerate_partial(
        current_entries=entries,
        locked_sessions=locked_sids,
        room_disruptions=r_dis
    )
    assert res["success"] is True

    # Validate with ConflictValidator
    test_vid = "V_TEMP_AUDIT"
    db.save_timetable_version(test_vid, "Audit Test", res["entries"], res["metrics"])
    validator = ConflictValidator(db)
    audit = validator.validate(test_vid)
    assert audit["hard_conflicts"] == 0
    assert audit["is_valid"] is True

def test_graceful_infeasibility_handling(setup_optimizer):
    db, opt, entries = setup_optimizer

    # Lock ALL sessions and block the faculty on their ONLY scheduled slots for all days
    locked_sids = {e["session_id"] for e in entries}
    first = entries[0]
    # Block faculty for Entire Week
    f_dis = [{"faculty_id": first["faculty_id"], "day": "All", "period_id": "Entire Day"}]

    res = opt.regenerate_partial(
        current_entries=entries,
        locked_sessions=locked_sids,
        faculty_disruptions=f_dis
    )
    # Must fail gracefully with clear explanation, without raising an unhandled exception
    assert res["success"] is False or len(res.get("diagnostics", [])) > 0
    assert "status" in res

def test_ui_grid_badges_rendering(setup_optimizer):
    db, _, entries = setup_optimizer
    entries_df = pd.DataFrame(entries)
    students_df = db.get_students()
    enroll_df = db.get_student_enrollments()

    # Pick CSE course sessions
    cse_entries = [e for e in entries if e["course_id"] in ["C101", "C102", "C103", "C104", "C105"]]
    assert len(cse_entries) >= 2

    locked_sample = {cse_entries[0]["session_id"]}
    moved_sample = {cse_entries[1]["session_id"]}

    grid_dept = build_department_cohort_grid(
        entries_df, "CSE", students_df, enroll_df,
        locked_sessions=locked_sample,
        moved_sessions=moved_sample
    )
    html_dept = grid_dept.to_html(escape=False)
    assert "Locked" in html_dept or "🔒" in html_dept
    assert "Moved" in html_dept or "✨" in html_dept
