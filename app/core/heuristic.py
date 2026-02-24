from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from time import perf_counter

from app.core.models import ScheduleAssignment, SchedulingInput
from app.core.objective import assignment_local_score, compute_objective_breakdown
from app.core.session_utils import CourseSession, expand_course_sessions


@dataclass
class HeuristicSolveOutput:
    status: str
    assignments: list[ScheduleAssignment]
    notes: list[str]
    objective_breakdown: dict[str, float]
    runtime_seconds: float


def _build_feasible_candidates(
    data: SchedulingInput,
    sessions: list[CourseSession],
) -> dict[str, list[tuple[str, str]]]:
    instructor_by_id = {instructor.id: instructor for instructor in data.instructors}
    room_by_id = {room.id: room for room in data.rooms}
    slots = sorted(data.time_slots, key=lambda item: item.order)

    feasible: dict[str, list[tuple[str, str]]] = {}

    for session in sessions:
        instructor = instructor_by_id.get(session.instructor_id)
        if instructor is None:
            feasible[session.session_id] = []
            continue

        instructor_available = set(instructor.available_time_slots)
        allowed_slots = set(session.allowed_time_slots)

        options: list[tuple[str, str]] = []
        for room in room_by_id.values():
            if room.capacity < session.enrollment:
                continue
            if not set(session.required_features).issubset(set(room.features)):
                continue

            for slot in slots:
                if instructor_available and slot.id not in instructor_available:
                    continue
                if allowed_slots and slot.id not in allowed_slots:
                    continue
                options.append((room.id, slot.id))

        feasible[session.session_id] = options

    return feasible


def solve_with_heuristic(data: SchedulingInput) -> HeuristicSolveOutput:
    start = perf_counter()

    sessions = expand_course_sessions(data.courses)
    feasible_candidates = _build_feasible_candidates(data, sessions)

    instructor_by_id = {instructor.id: instructor for instructor in data.instructors}
    room_by_id = {room.id: room for room in data.rooms}
    slot_by_id = {slot.id: slot for slot in data.time_slots}

    occupied_room_slot: set[tuple[str, str]] = set()
    occupied_instructor_slot: set[tuple[str, str]] = set()
    course_days_used: dict[str, set[str]] = defaultdict(set)
    instructor_day_count: dict[tuple[str, str], int] = defaultdict(int)
    cluster_days_used: dict[str, set[str]] = defaultdict(set)

    sorted_sessions = sorted(
        sessions,
        key=lambda session: (len(feasible_candidates[session.session_id]), -session.priority),
    )

    assignments: list[ScheduleAssignment] = []
    unscheduled: list[str] = []

    for session in sorted_sessions:
        candidates = feasible_candidates[session.session_id]
        if not candidates:
            unscheduled.append(session.session_id)
            continue

        instructor = instructor_by_id.get(session.instructor_id)
        if instructor is None:
            unscheduled.append(session.session_id)
            continue

        best_option: tuple[str, str] | None = None
        best_score: int | None = None

        for room_id, slot_id in candidates:
            slot = slot_by_id[slot_id]
            room = room_by_id[room_id]

            if (room_id, slot_id) in occupied_room_slot:
                continue
            if (session.instructor_id, slot_id) in occupied_instructor_slot:
                continue
            if session.avoid_same_day_sessions and slot.day in course_days_used[session.course_id]:
                continue

            max_per_day = instructor.max_sessions_per_day
            if max_per_day is not None:
                if instructor_day_count[(session.instructor_id, slot.day)] >= max_per_day:
                    continue

            cluster_days = cluster_days_used.get(session.cluster_tag, set())
            score = assignment_local_score(
                session=session,
                instructor_preferred_slots=set(instructor.preferred_time_slots),
                room_capacity=room.capacity,
                time_slot_id=slot_id,
                slot_day=slot.day,
                weights=data.options.objective_weights,
                existing_cluster_days=cluster_days,
            )

            if best_score is None or score > best_score:
                best_score = score
                best_option = (room_id, slot_id)

        if best_option is None:
            unscheduled.append(session.session_id)
            continue

        room_id, slot_id = best_option
        slot = slot_by_id[slot_id]

        assignments.append(
            ScheduleAssignment(
                session_id=session.session_id,
                course_id=session.course_id,
                instructor_id=session.instructor_id,
                room_id=room_id,
                time_slot_id=slot_id,
            )
        )

        occupied_room_slot.add((room_id, slot_id))
        occupied_instructor_slot.add((session.instructor_id, slot_id))
        course_days_used[session.course_id].add(slot.day)
        instructor_day_count[(session.instructor_id, slot.day)] += 1
        if session.cluster_tag:
            cluster_days_used[session.cluster_tag].add(slot.day)

    objective_breakdown = compute_objective_breakdown(
        data=data,
        assignments=assignments,
        weights=data.options.objective_weights,
    )

    notes: list[str] = [
        "Fallback heuristic solver executed.",
        "Sessions are scheduled greedily by constrainedness and local weighted score.",
    ]

    status = "fallback"
    if unscheduled:
        status = "fallback_partial"
        notes.append(
            f"{len(unscheduled)} session(s) were left unscheduled due to constraint overload."
        )

    return HeuristicSolveOutput(
        status=status,
        assignments=assignments,
        notes=notes,
        objective_breakdown=objective_breakdown,
        runtime_seconds=perf_counter() - start,
    )
