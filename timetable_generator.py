import time
import json
from typing import Dict, List, Tuple, Any, Optional, Set
import pandas as pd
from ortools.sat.python import cp_model

class TimetableOptimizer:
    """
    NEP 2020 Aligned Multidisciplinary Timetable Generator using Google OR-Tools CP-SAT.
    Handles hard and soft constraints, lab block pairing, multi-department electives,
    conflict-free student cohort schedules, and detailed infeasibility diagnostics.
    """
    def __init__(self, db_manager):
        self.db = db_manager
        self.days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
        self.periods = ["P1", "P2", "P3", "P4", "P5", "P6"]
        self.num_days = len(self.days)
        self.num_periods = len(self.periods)
        self.total_slots = self.num_days * self.num_periods
        # Period mapping
        self.period_order = {p: i for i, p in enumerate(self.periods)}
        self.day_order = {d: i for i, d in enumerate(self.days)}

    def _load_data(self):
        """Loads all academic data from the database."""
        courses_df = self.db.get_courses()
        rooms_df = self.db.get_classrooms()
        faculty_df = self.db.get_faculty()
        avail_df = self.db.get_faculty_availability()
        enroll_df = self.db.get_student_enrollments()
        students_df = self.db.get_students()
        time_slots_df = self.db.get_time_slots()
        constraints_df = self.db.get_constraints()

        return {
            "courses": courses_df,
            "classrooms": rooms_df,
            "faculty": faculty_df,
            "availability": avail_df,
            "enrollments": enroll_df,
            "students": students_df,
            "time_slots": time_slots_df,
            "constraints": constraints_df
        }

    def _get_constraint_weights(self, constraints_df: pd.DataFrame) -> Dict[str, Any]:
        """Extracts configured weights and limits from constraints table."""
        weights = {
            "solver_time_limit_seconds": 30,
            "soft_workload_weight": 5,
            "soft_student_gap_weight": 8,
            "soft_room_utilization_weight": 3,
            "max_consecutive_periods_faculty": 3,
            "balance_faculty_workload": True,
            "minimize_student_gaps": True
        }
        for _, row in constraints_df.iterrows():
            name = str(row["constraint_name"]).strip()
            val = str(row["constraint_value"]).strip()
            if name == "solver_time_limit_seconds":
                weights["solver_time_limit_seconds"] = int(float(val))
            elif name == "soft_workload_weight":
                weights["soft_workload_weight"] = int(float(val))
            elif name == "soft_student_gap_weight":
                weights["soft_student_gap_weight"] = int(float(val))
            elif name == "soft_room_utilization_weight":
                weights["soft_room_utilization_weight"] = int(float(val))
            elif name == "max_consecutive_periods_faculty":
                weights["max_consecutive_periods_faculty"] = int(float(val))
            elif name == "balance_faculty_workload":
                weights["balance_faculty_workload"] = (val.lower() == "true")
            elif name == "minimize_student_gaps":
                weights["minimize_student_gaps"] = (val.lower() == "true")
        return weights

    def diagnose_infeasibility(self, data: Dict[str, pd.DataFrame]) -> List[Dict[str, Any]]:
        """
        Pre-flight and post-flight diagnostic engine.
        Checks for impossible constraints, oversubscribed faculty, insufficient room capacities,
        and tight student group workloads before and after solver execution.
        """
        diagnostics = []
        courses_df = data["courses"]
        rooms_df = data["classrooms"]
        faculty_df = data["faculty"]
        avail_df = data["availability"]
        enroll_df = data["enrollments"]

        # 1. Check Course Room Requirements
        for _, c in courses_df.iterrows():
            cid = c["course_id"]
            cname = c["course_name"]
            rtype = c["required_room_type"]
            enrol = int(c["expected_enrolment"])
            # Match rooms
            valid_rooms = rooms_df[
                (rooms_df["room_type"] == rtype) & (rooms_df["capacity"] >= enrol)
            ]
            if valid_rooms.empty:
                # Check if any room has right type even with smaller capacity
                same_type = rooms_df[rooms_df["room_type"] == rtype]
                if same_type.empty:
                    diagnostics.append({
                        "category": "Classroom Deficiency",
                        "severity": "CRITICAL",
                        "item": f"Course {cid} ({cname})",
                        "reason": f"Required room type '{rtype}' does not exist in the institution.",
                        "suggestion": f"Add a classroom with room_type='{rtype}' or update course room requirements."
                    })
                else:
                    max_cap = same_type["capacity"].max()
                    diagnostics.append({
                        "category": "Capacity Bottleneck",
                        "severity": "CRITICAL",
                        "item": f"Course {cid} ({cname})",
                        "reason": f"Course has {enrol} enrolled students, but largest '{rtype}' has capacity of {max_cap}.",
                        "suggestion": f"Split the class into multiple batches or increase room capacity."
                    })

        # 2. Check Faculty Teaching Load vs Availability
        avail_map = {}
        for _, row in avail_df.iterrows():
            avail_map[(row["faculty_id"], row["day"], row["period_id"])] = int(row["is_available"])

        for _, f in faculty_df.iterrows():
            fid = f["faculty_id"]
            fname = f["faculty_name"]
            max_w = int(f["max_weekly_periods"])

            # Calculate total periods needed for assigned courses
            assigned_c = courses_df[courses_df["faculty_id"] == fid]
            req_periods = sum(int(r["weekly_sessions"]) * int(r["duration_periods"]) for _, r in assigned_c.iterrows())

            # Count available slots
            avail_slots = sum(
                avail_map.get((fid, d, p), 1)
                for d in self.days for p in self.periods
            )

            if req_periods > max_w:
                diagnostics.append({
                    "category": "Faculty Overload",
                    "severity": "CRITICAL",
                    "item": f"Faculty {fname} ({fid})",
                    "reason": f"Assigned courses require {req_periods} periods/week, exceeding max weekly periods ({max_w}).",
                    "suggestion": f"Reassign one of the courses ({', '.join(assigned_c['course_id'])}) to another faculty member."
                })

            if req_periods > avail_slots:
                diagnostics.append({
                    "category": "Faculty Availability Shortage",
                    "severity": "CRITICAL",
                    "item": f"Faculty {fname} ({fid})",
                    "reason": f"Needs {req_periods} periods/week but is only marked available for {avail_slots} slots.",
                    "suggestion": f"Increase faculty availability in Data Management or reassign courses."
                })

        # 3. Lab Session Availability check (duration 2 needs consecutive slots)
        lab_courses = courses_df[courses_df["duration_periods"] == 2]
        for _, lc in lab_courses.iterrows():
            fid = lc["faculty_id"]
            fname = faculty_df[faculty_df["faculty_id"] == fid]["faculty_name"].values[0] if not faculty_df[faculty_df["faculty_id"] == fid].empty else fid
            # Check how many 2-period blocks are available
            valid_2period_blocks = 0
            for d in self.days:
                for p_idx in [0, 2, 4]:
                    p1 = self.periods[p_idx]
                    p2 = self.periods[p_idx + 1]
                    if avail_map.get((fid, d, p1), 1) == 1 and avail_map.get((fid, d, p2), 1) == 1:
                        valid_2period_blocks += 1
            if valid_2period_blocks < int(lc["weekly_sessions"]):
                diagnostics.append({
                    "category": "Lab Scheduling Blockage",
                    "severity": "CRITICAL",
                    "item": f"Laboratory {lc['course_id']} ({lc['course_name']})",
                    "reason": f"Requires {lc['weekly_sessions']} two-period lab sessions, but faculty {fname} only has {valid_2period_blocks} valid double-period slots available.",
                    "suggestion": f"Ensure faculty {fname} has consecutive availability in morning (P1-P2, P3-P4) or afternoon (P5-P6)."
                })

        # 4. Check Student Workload & Clashes
        if not enroll_df.empty:
            std_loads = enroll_df.groupby("student_id").size()
            max_std_courses = std_loads.max()
            if max_std_courses > 12:
                diagnostics.append({
                    "category": "Student Course Overload",
                    "severity": "WARNING",
                    "item": f"Students with {max_std_courses} courses",
                    "reason": "Some students are enrolled in an extraordinarily high number of courses.",
                    "suggestion": "Verify student course registrations."
                })

        return diagnostics

    def generate(self) -> Dict[str, Any]:
        """
        Executes Google OR-Tools CP-SAT timetable generation.
        Returns full results dictionary with status, entries, metrics, and diagnostics.
        """
        start_time = time.time()
        data = self._load_data()
        courses_df = data["courses"]
        rooms_df = data["classrooms"]
        faculty_df = data["faculty"]
        avail_df = data["availability"]
        enroll_df = data["enrollments"]
        time_slots_df = data["time_slots"]
        constraints_df = data["constraints"]

        weights = self._get_constraint_weights(constraints_df)

        if courses_df.empty or rooms_df.empty or time_slots_df.empty:
            return {
                "success": False,
                "status": "DATA_MISSING",
                "message": "Academic dataset is incomplete. Please import the Excel workbook first.",
                "diagnostics": [{"category": "Data Missing", "severity": "CRITICAL", "item": "Database", "reason": "No courses or classrooms found.", "suggestion": "Upload workbook in Data Management."}],
                "entries": [],
                "metrics": {}
            }

        # Run pre-flight diagnostics
        pre_diagnostics = self.diagnose_infeasibility(data)
        critical_issues = [d for d in pre_diagnostics if d["severity"] == "CRITICAL"]
        if critical_issues:
            return {
                "success": False,
                "status": "INFEASIBLE_PRECHECK",
                "message": f"Pre-solve validation detected {len(critical_issues)} critical conflict(s).",
                "diagnostics": pre_diagnostics,
                "entries": [],
                "metrics": {"duration_seconds": round(time.time() - start_time, 2)}
            }

        # Build Availability Lookup
        avail_map = {}
        for _, row in avail_df.iterrows():
            avail_map[(row["faculty_id"], row["day"], row["period_id"])] = int(row["is_available"])

        # Map Time Slot IDs: (day, period_id) -> time_slot_id
        slot_id_map = {}
        for _, row in time_slots_df.iterrows():
            slot_id_map[(row["day"], row["period_id"])] = row["time_slot_id"]

        # Student Enrollments & Course Conflict Graph
        course_students = {}
        if not enroll_df.empty:
            course_students = enroll_df.groupby("course_id")["student_id"].apply(set).to_dict()

        # Expand courses into sessions
        sessions = []
        rooms = rooms_df.to_dict(orient="records")

        for _, row in courses_df.iterrows():
            cid = str(row["course_id"]).strip()
            w = int(row["weekly_sessions"])
            dur = int(row["duration_periods"])
            fid = str(row["faculty_id"]).strip()
            rtype = str(row["required_room_type"]).strip()
            enrol = int(row["expected_enrolment"])
            actual_enrol = len(course_students.get(cid, set()))
            eff_enrol = max(enrol, actual_enrol) if actual_enrol > 0 else enrol

            for s_idx in range(w):
                sessions.append({
                    "session_id": f"{cid}_S{s_idx + 1}",
                    "course_id": cid,
                    "session_idx": s_idx,
                    "duration": dur,
                    "faculty_id": fid,
                    "required_room_type": rtype,
                    "enrolment": eff_enrol
                })

        # Determine valid rooms and slots for each session
        valid_rooms_for_session = {}
        valid_slots_for_session = {}

        for s in sessions:
            sid = s["session_id"]
            dur = s["duration"]
            fid = s["faculty_id"]

            # Valid rooms
            v_rooms = [
                r["classroom_id"] for r in rooms
                if r["room_type"] == s["required_room_type"] and r["capacity"] >= s["enrolment"]
            ]
            if not v_rooms:
                # Fallback to capacity >= actual enrolment if present
                act_e = len(course_students.get(s["course_id"], set()))
                v_rooms = [
                    r["classroom_id"] for r in rooms
                    if r["room_type"] == s["required_room_type"] and r["capacity"] >= act_e
                ]
            valid_rooms_for_session[sid] = v_rooms

            # Valid starting slots
            v_slots = []
            for d_idx, day in enumerate(self.days):
                for p_idx, period in enumerate(self.periods):
                    slot_num = d_idx * self.num_periods + p_idx
                    if dur == 1:
                        if avail_map.get((fid, day, period), 1) == 1:
                            v_slots.append(slot_num)
                    elif dur == 2:
                        # 2-period labs must start at P1 (0), P3 (2), or P5 (4)
                        if p_idx in [0, 2, 4]:
                            p_next = self.periods[p_idx + 1]
                            if avail_map.get((fid, day, period), 1) == 1 and avail_map.get((fid, day, p_next), 1) == 1:
                                v_slots.append(slot_num)
            valid_slots_for_session[sid] = v_slots

        # Initialize CP-SAT Model
        model = cp_model.CpModel()
        x = {}

        for s in sessions:
            sid = s["session_id"]
            v_slots = valid_slots_for_session[sid]
            v_rooms = valid_rooms_for_session[sid]

            if not v_slots or not v_rooms:
                pre_diagnostics.append({
                    "category": "Infeasible Session Domains",
                    "severity": "CRITICAL",
                    "item": f"Session {sid}",
                    "reason": f"No available time slots ({len(v_slots)}) or rooms ({len(v_rooms)}).",
                    "suggestion": "Relax room requirements or expand faculty availability."
                })
                return {
                    "success": False,
                    "status": "INFEASIBLE",
                    "message": f"Session {sid} has no eligible slots or rooms.",
                    "diagnostics": pre_diagnostics,
                    "entries": [],
                    "metrics": {}
                }

            s_vars = []
            for slot in v_slots:
                for room in v_rooms:
                    v = model.NewBoolVar(f"x_{sid}_{slot}_{room}")
                    x[(sid, slot, room)] = v
                    s_vars.append(v)

            # Hard Constraint: Every session must be scheduled exactly once
            model.AddExactlyOne(s_vars)

        # -------------------------------------------------------------
        # HARD CONSTRAINTS
        # -------------------------------------------------------------

        # 1. Classroom Clashes: A classroom can host at most one session per period
        for r in rooms:
            rid = r["classroom_id"]
            for t in range(self.total_slots):
                room_vars = []
                for s in sessions:
                    sid = s["session_id"]
                    dur = s["duration"]
                    if rid not in valid_rooms_for_session[sid]:
                        continue
                    if dur == 1:
                        if (sid, t, rid) in x:
                            room_vars.append(x[(sid, t, rid)])
                    elif dur == 2:
                        if (sid, t, rid) in x:
                            room_vars.append(x[(sid, t, rid)])
                        if (t % self.num_periods > 0) and (sid, t - 1, rid) in x:
                            room_vars.append(x[(sid, t - 1, rid)])
                if len(room_vars) > 1:
                    model.Add(sum(room_vars) <= 1)

        # 2. Faculty Clashes: A faculty member cannot teach > 1 session in any period
        unique_faculty = faculty_df["faculty_id"].unique()
        for fid in unique_faculty:
            f_sessions = [s for s in sessions if s["faculty_id"] == fid]
            if len(f_sessions) <= 1:
                continue
            for t in range(self.total_slots):
                f_vars = []
                for s in f_sessions:
                    sid = s["session_id"]
                    dur = s["duration"]
                    for rid in valid_rooms_for_session[sid]:
                        if dur == 1:
                            if (sid, t, rid) in x:
                                f_vars.append(x[(sid, t, rid)])
                        elif dur == 2:
                            if (sid, t, rid) in x:
                                f_vars.append(x[(sid, t, rid)])
                            if (t % self.num_periods > 0) and (sid, t - 1, rid) in x:
                                f_vars.append(x[(sid, t - 1, rid)])
                if len(f_vars) > 1:
                    model.Add(sum(f_vars) <= 1)

        # 3. Student Clashes: If courses share students, they cannot overlap in any period
        cids = list(course_students.keys())
        for i in range(len(cids)):
            for j in range(i + 1, len(cids)):
                c1, c2 = cids[i], cids[j]
                if course_students[c1].intersection(course_students[c2]):
                    s1_list = [s for s in sessions if s["course_id"] == c1]
                    s2_list = [s for s in sessions if s["course_id"] == c2]
                    for t in range(self.total_slots):
                        c_overlap_vars = []
                        for s in s1_list:
                            sid = s["session_id"]
                            dur = s["duration"]
                            for rid in valid_rooms_for_session[sid]:
                                if dur == 1 and (sid, t, rid) in x:
                                    c_overlap_vars.append(x[(sid, t, rid)])
                                elif dur == 2:
                                    if (sid, t, rid) in x:
                                        c_overlap_vars.append(x[(sid, t, rid)])
                                    if (t % self.num_periods > 0) and (sid, t - 1, rid) in x:
                                        c_overlap_vars.append(x[(sid, t - 1, rid)])
                        for s in s2_list:
                            sid = s["session_id"]
                            dur = s["duration"]
                            for rid in valid_rooms_for_session[sid]:
                                if dur == 1 and (sid, t, rid) in x:
                                    c_overlap_vars.append(x[(sid, t, rid)])
                                elif dur == 2:
                                    if (sid, t, rid) in x:
                                        c_overlap_vars.append(x[(sid, t, rid)])
                                    if (t % self.num_periods > 0) and (sid, t - 1, rid) in x:
                                        c_overlap_vars.append(x[(sid, t - 1, rid)])
                        if len(c_overlap_vars) > 1:
                            model.Add(sum(c_overlap_vars) <= 1)

        # 4. Same Course Distribution: At most 1 lecture session per course per day
        courses_grouped = {}
        for s in sessions:
            courses_grouped.setdefault(s["course_id"], []).append(s)

        for cid, s_list in courses_grouped.items():
            if len(s_list) > 1:
                for d in range(self.num_days):
                    day_vars = []
                    for p in range(self.num_periods):
                        slot = d * self.num_periods + p
                        for s in s_list:
                            sid = s["session_id"]
                            for rid in valid_rooms_for_session[sid]:
                                if (sid, slot, rid) in x:
                                    day_vars.append(x[(sid, slot, rid)])
                    model.Add(sum(day_vars) <= 1)

        # -------------------------------------------------------------
        # SOFT CONSTRAINTS & OBJECTIVE FUNCTION
        # -------------------------------------------------------------
        objective_terms = []

        # Soft 1: Balance Faculty Workload across days
        # Penalize having more than 3 teaching periods in a single day for any faculty
        if weights["balance_faculty_workload"]:
            w_fac = weights["soft_workload_weight"]
            for fid in unique_faculty:
                f_sessions = [s for s in sessions if s["faculty_id"] == fid]
                if not f_sessions:
                    continue
                for d in range(self.num_days):
                    daily_periods = []
                    for p in range(self.num_periods):
                        slot = d * self.num_periods + p
                        for s in f_sessions:
                            sid = s["session_id"]
                            dur = s["duration"]
                            for rid in valid_rooms_for_session[sid]:
                                if dur == 1 and (sid, slot, rid) in x:
                                    daily_periods.append(x[(sid, slot, rid)])
                                elif dur == 2:
                                    if (sid, slot, rid) in x:
                                        daily_periods.append(x[(sid, slot, rid)])
                                    if p > 0 and (sid, slot - 1, rid) in x:
                                        daily_periods.append(x[(sid, slot - 1, rid)])
                    # If faculty has > 3 periods in a single day, add soft penalty
                    excess_var = model.NewIntVar(0, self.num_periods, f"excess_load_{fid}_{d}")
                    model.Add(excess_var >= sum(daily_periods) - 3)
                    objective_terms.append(-w_fac * excess_var)

        # Soft 2: Reduce Student Timetable Gaps
        # Prefer classes to be clustered in morning/afternoon rather than fragmented
        if weights["minimize_student_gaps"]:
            w_gap = weights["soft_student_gap_weight"]
            # Encourage sessions in prime teaching slots (P1 to P4) over P6
            for s in sessions:
                sid = s["session_id"]
                for slot in valid_slots_for_session[sid]:
                    p = slot % self.num_periods
                    # Preference bonus for earlier periods
                    bonus = (self.num_periods - p)
                    for rid in valid_rooms_for_session[sid]:
                        if (sid, slot, rid) in x:
                            objective_terms.append(bonus * x[(sid, slot, rid)])

        # Maximize objective
        if objective_terms:
            model.Maximize(sum(objective_terms))

        # -------------------------------------------------------------
        # SOLVER EXECUTION
        # -------------------------------------------------------------
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = float(weights["solver_time_limit_seconds"])
        solver.parameters.num_search_workers = 4

        status = solver.Solve(model)
        status_name = solver.StatusName(status)
        solve_duration = round(time.time() - start_time, 2)

        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            entries = []
            for s in sessions:
                sid = s["session_id"]
                dur = s["duration"]
                for slot in valid_slots_for_session[sid]:
                    for rid in valid_rooms_for_session[sid]:
                        if (sid, slot, rid) in x and solver.Value(x[(sid, slot, rid)]) == 1:
                            d_idx = slot // self.num_periods
                            p_idx = slot % self.num_periods
                            day = self.days[d_idx]
                            period_id = self.periods[p_idx]
                            ts_id = slot_id_map.get((day, period_id), f"{day[:3].upper()}_{period_id}")

                            entries.append({
                                "session_id": sid,
                                "course_id": s["course_id"],
                                "faculty_id": s["faculty_id"],
                                "classroom_id": rid,
                                "day": day,
                                "period_id": period_id,
                                "duration_periods": dur,
                                "time_slot_id": ts_id
                            })

            # Calculate detailed metrics
            scheduled_count = len(entries)
            total_required = len(sessions)
            fac_workload = {}
            for e in entries:
                fid = e["faculty_id"]
                fac_workload[fid] = fac_workload.get(fid, 0) + e["duration_periods"]

            room_usage = {}
            for e in entries:
                rid = e["classroom_id"]
                room_usage[rid] = room_usage.get(rid, 0) + e["duration_periods"]

            metrics = {
                "solver_status": status_name,
                "duration_seconds": solve_duration,
                "total_required_sessions": total_required,
                "scheduled_sessions": scheduled_count,
                "unscheduled_sessions": total_required - scheduled_count,
                "conflict_count": 0,
                "faculty_workload": fac_workload,
                "room_utilization": room_usage,
                "objective_value": solver.ObjectiveValue() if status == cp_model.OPTIMAL else 0
            }

            return {
                "success": True,
                "status": status_name,
                "message": f"Valid timetable successfully generated in {solve_duration}s ({status_name}).",
                "entries": entries,
                "metrics": metrics,
                "diagnostics": []
            }
        else:
            # Solver failed to find solution
            post_diagnostics = self.diagnose_infeasibility(data)
            return {
                "success": False,
                "status": status_name,
                "message": f"Solver could not find a valid timetable ({status_name}). Identified potential bottlenecks below.",
                "diagnostics": post_diagnostics,
                "entries": [],
                "metrics": {
                    "solver_status": status_name,
                    "duration_seconds": solve_duration,
                    "total_required_sessions": len(sessions),
                    "scheduled_sessions": 0,
                    "unscheduled_sessions": len(sessions)
                }
            }
