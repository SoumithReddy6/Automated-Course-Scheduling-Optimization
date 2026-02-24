from __future__ import annotations

from collections import defaultdict
from time import perf_counter
from typing import Literal

from ortools.sat.python import cp_model

from app.core.heuristic import solve_with_heuristic
from app.core.metrics import build_metrics
from app.core.models import ScheduleAssignment, ScheduleResult, SchedulingInput, ValidationReport
from app.core.objective import compute_objective_breakdown
from app.core.session_utils import expand_course_sessions
from app.core.validation import validate_schedule

SolverMode = Literal["auto", "cp_sat", "heuristic"]


def _cp_status_to_text(status: int) -> str:
    mapping = {
        cp_model.OPTIMAL: "optimal",
        cp_model.FEASIBLE: "feasible",
        cp_model.INFEASIBLE: "infeasible",
        cp_model.MODEL_INVALID: "model_invalid",
        cp_model.UNKNOWN: "unknown",
    }
    return mapping.get(status, "unknown")


def _build_result(
    *,
    status: str,
    solver_name: Literal["cp_sat", "heuristic"],
    runtime_seconds: float,
    assignments: list[ScheduleAssignment],
    notes: list[str],
    data: SchedulingInput,
) -> tuple[ScheduleResult, ValidationReport]:
    validation = validate_schedule(data, assignments)
    objective_breakdown = compute_objective_breakdown(
        data=data,
        assignments=assignments,
        weights=data.options.objective_weights,
    )
    metrics = build_metrics(
        data=data,
        assignments=assignments,
        validation=validation,
        objective_breakdown=objective_breakdown,
    )

    result = ScheduleResult(
        status=status,
        solver=solver_name,
        runtime_seconds=round(runtime_seconds, 4),
        objective_value=objective_breakdown.get("total", 0.0),
        assignments=sorted(assignments, key=lambda item: item.session_id),
        metrics=metrics,
        notes=notes,
    )
    return result, validation


def _solve_with_cp_sat(
    data: SchedulingInput,
) -> tuple[str, float, list[ScheduleAssignment], list[str]]:
    start = perf_counter()
    notes: list[str] = []

    sessions = expand_course_sessions(data.courses)
    rooms = list(data.rooms)
    slots = sorted(data.time_slots, key=lambda item: item.order)
    days = sorted({slot.day for slot in slots})

    instructor_by_id = {instructor.id: instructor for instructor in data.instructors}

    unknown_instructors = {
        course.instructor_id
        for course in data.courses
        if course.instructor_id not in instructor_by_id
    }
    if unknown_instructors:
        notes.append(
            "Unknown instructor id(s) detected in course input: "
            + ", ".join(sorted(unknown_instructors))
        )
        return "model_invalid", perf_counter() - start, [], notes

    model = cp_model.CpModel()

    x: dict[tuple[str, str, str, str, str], cp_model.IntVar] = {}
    vars_by_session: dict[str, list[cp_model.IntVar]] = defaultdict(list)
    vars_by_room_slot: dict[tuple[str, str], list[cp_model.IntVar]] = defaultdict(list)
    vars_by_instructor_slot: dict[tuple[str, str], list[cp_model.IntVar]] = defaultdict(list)
    vars_by_course_day: dict[tuple[str, str], list[cp_model.IntVar]] = defaultdict(list)
    vars_by_instructor_day: dict[tuple[str, str], list[cp_model.IntVar]] = defaultdict(list)
    vars_by_cluster_day: dict[tuple[str, str], list[cp_model.IntVar]] = defaultdict(list)

    instructor_pref_terms: list[cp_model.LinearExpr] = []
    room_eff_terms: list[cp_model.LinearExpr] = []
    priority_terms: list[cp_model.LinearExpr] = []

    cluster_session_count: dict[str, int] = defaultdict(int)

    for session in sessions:
        instructor = instructor_by_id[session.instructor_id]
        instructor_available = set(instructor.available_time_slots)
        course_allowed_slots = set(session.allowed_time_slots)

        if session.cluster_tag:
            cluster_session_count[session.cluster_tag] += 1

        for room in rooms:
            if room.capacity < session.enrollment:
                continue
            if not set(session.required_features).issubset(set(room.features)):
                continue

            for slot in slots:
                if instructor_available and slot.id not in instructor_available:
                    continue
                if course_allowed_slots and slot.id not in course_allowed_slots:
                    continue

                key = (
                    session.session_id,
                    session.course_id,
                    session.instructor_id,
                    room.id,
                    slot.id,
                )
                var = model.NewBoolVar(
                    f"x_{session.session_id}_{room.id}_{slot.id}".replace(":", "_")
                )

                x[key] = var
                vars_by_session[session.session_id].append(var)
                vars_by_room_slot[(room.id, slot.id)].append(var)
                vars_by_instructor_slot[(session.instructor_id, slot.id)].append(var)
                vars_by_course_day[(session.course_id, slot.day)].append(var)
                vars_by_instructor_day[(session.instructor_id, slot.day)].append(var)

                if session.cluster_tag:
                    vars_by_cluster_day[(session.cluster_tag, slot.day)].append(var)

                if slot.id in instructor.preferred_time_slots:
                    instructor_pref_terms.append(var)

                utilization = int((session.enrollment / room.capacity) * 100)
                room_eff_terms.append(utilization * var)

                if session.preferred_time_slots and slot.id in session.preferred_time_slots:
                    priority_terms.append(session.priority * 20 * var)

    for session in sessions:
        vars_for_session = vars_by_session.get(session.session_id, [])
        if not vars_for_session:
            notes.append(
                f"No feasible assignment exists for session '{session.session_id}'."
            )
            return "infeasible", perf_counter() - start, [], notes
        model.Add(sum(vars_for_session) == 1)

    for vars_for_room_slot in vars_by_room_slot.values():
        if len(vars_for_room_slot) > 1:
            model.Add(sum(vars_for_room_slot) <= 1)

    for vars_for_instructor_slot in vars_by_instructor_slot.values():
        if len(vars_for_instructor_slot) > 1:
            model.Add(sum(vars_for_instructor_slot) <= 1)

    for course in data.courses:
        if not course.avoid_same_day_sessions or course.sessions_per_week <= 1:
            continue
        for day in days:
            day_vars = vars_by_course_day.get((course.id, day), [])
            if day_vars:
                model.Add(sum(day_vars) <= 1)

    for instructor in data.instructors:
        if instructor.max_sessions_per_day is None:
            continue
        for day in days:
            day_vars = vars_by_instructor_day.get((instructor.id, day), [])
            if day_vars:
                model.Add(sum(day_vars) <= instructor.max_sessions_per_day)

    cluster_used_day_vars: list[cp_model.IntVar] = []
    for (cluster_tag, _day), day_vars in vars_by_cluster_day.items():
        if cluster_session_count.get(cluster_tag, 0) <= 1:
            continue
        used_var = model.NewBoolVar(f"cluster_{cluster_tag}_{_day}".replace(":", "_"))
        for var in day_vars:
            model.Add(var <= used_var)
        model.Add(sum(day_vars) >= used_var)
        cluster_used_day_vars.append(used_var)

    weights = data.options.objective_weights

    objective_terms: list[cp_model.LinearExpr] = []
    objective_terms.extend(
        [100 * weights.instructor_preference * term for term in instructor_pref_terms]
    )
    objective_terms.extend([weights.room_efficiency * term for term in room_eff_terms])
    objective_terms.extend([weights.course_priority * term for term in priority_terms])
    objective_terms.extend(
        [-100 * weights.cluster_compactness * term for term in cluster_used_day_vars]
    )

    if objective_terms:
        model.Maximize(sum(objective_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = data.options.time_limit_seconds
    solver.parameters.num_search_workers = data.options.num_workers

    status_code = solver.Solve(model)
    status = _cp_status_to_text(status_code)

    assignments: list[ScheduleAssignment] = []
    if status in {"optimal", "feasible"}:
        for (
            session_id,
            course_id,
            instructor_id,
            room_id,
            time_slot_id,
        ), var in x.items():
            if solver.BooleanValue(var):
                assignments.append(
                    ScheduleAssignment(
                        session_id=session_id,
                        course_id=course_id,
                        instructor_id=instructor_id,
                        room_id=room_id,
                        time_slot_id=time_slot_id,
                    )
                )

    return status, perf_counter() - start, assignments, notes


def solve_schedule(
    data: SchedulingInput,
    solver_mode: SolverMode = "auto",
) -> tuple[ScheduleResult, ValidationReport]:
    if solver_mode == "heuristic":
        heuristic_output = solve_with_heuristic(data)
        return _build_result(
            status=heuristic_output.status,
            solver_name="heuristic",
            runtime_seconds=heuristic_output.runtime_seconds,
            assignments=heuristic_output.assignments,
            notes=heuristic_output.notes,
            data=data,
        )

    cp_status, cp_runtime, cp_assignments, cp_notes = _solve_with_cp_sat(data)

    if cp_status in {"optimal", "feasible"}:
        return _build_result(
            status=cp_status,
            solver_name="cp_sat",
            runtime_seconds=cp_runtime,
            assignments=cp_assignments,
            notes=cp_notes,
            data=data,
        )

    if solver_mode == "auto" and data.options.enable_fallback:
        heuristic_output = solve_with_heuristic(data)
        notes = [f"CP-SAT status: {cp_status}. Triggering fallback heuristic."]
        notes.extend(cp_notes)
        notes.extend(heuristic_output.notes)
        return _build_result(
            status=heuristic_output.status,
            solver_name="heuristic",
            runtime_seconds=cp_runtime + heuristic_output.runtime_seconds,
            assignments=heuristic_output.assignments,
            notes=notes,
            data=data,
        )

    return _build_result(
        status=cp_status,
        solver_name="cp_sat",
        runtime_seconds=cp_runtime,
        assignments=cp_assignments,
        notes=cp_notes,
        data=data,
    )
