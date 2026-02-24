from __future__ import annotations

from app.core.models import ObjectiveWeights, ScheduleAssignment, SchedulingInput
from app.core.session_utils import CourseSession, expand_course_sessions


def assignment_local_score(
    session: CourseSession,
    instructor_preferred_slots: set[str],
    room_capacity: int,
    time_slot_id: str,
    slot_day: str,
    weights: ObjectiveWeights,
    existing_cluster_days: set[str],
) -> int:
    score = 0

    if time_slot_id in instructor_preferred_slots:
        score += 100 * weights.instructor_preference

    if room_capacity > 0:
        utilization = int((session.enrollment / room_capacity) * 100)
        score += utilization * weights.room_efficiency

    if session.preferred_time_slots and time_slot_id in session.preferred_time_slots:
        score += session.priority * 20 * weights.course_priority

    if session.cluster_tag:
        if existing_cluster_days:
            if slot_day in existing_cluster_days:
                score += 50 * weights.cluster_compactness
            else:
                score -= 100 * weights.cluster_compactness

    return score


def compute_objective_breakdown(
    data: SchedulingInput,
    assignments: list[ScheduleAssignment],
    weights: ObjectiveWeights,
) -> dict[str, float]:
    sessions = expand_course_sessions(data.courses)
    session_by_id = {session.session_id: session for session in sessions}
    instructor_by_id = {instructor.id: instructor for instructor in data.instructors}
    room_by_id = {room.id: room for room in data.rooms}
    slot_by_id = {slot.id: slot for slot in data.time_slots}

    instructor_component = 0
    room_component = 0
    priority_component = 0

    cluster_days: dict[str, set[str]] = {}
    cluster_counts: dict[str, int] = {}

    for assignment in assignments:
        session = session_by_id.get(assignment.session_id)
        instructor = instructor_by_id.get(assignment.instructor_id)
        room = room_by_id.get(assignment.room_id)
        slot = slot_by_id.get(assignment.time_slot_id)

        if not session or not instructor or not room or not slot:
            continue

        if assignment.time_slot_id in instructor.preferred_time_slots:
            instructor_component += 100 * weights.instructor_preference

        utilization = int((session.enrollment / room.capacity) * 100)
        room_component += utilization * weights.room_efficiency

        if session.preferred_time_slots and assignment.time_slot_id in session.preferred_time_slots:
            priority_component += session.priority * 20 * weights.course_priority

        if session.cluster_tag:
            cluster_days.setdefault(session.cluster_tag, set()).add(slot.day)
            cluster_counts[session.cluster_tag] = cluster_counts.get(session.cluster_tag, 0) + 1

    cluster_penalty_units = sum(
        len(days)
        for tag, days in cluster_days.items()
        if cluster_counts.get(tag, 0) > 1
    )
    cluster_component = -(cluster_penalty_units * 100 * weights.cluster_compactness)

    total = instructor_component + room_component + priority_component + cluster_component

    return {
        "instructor_preference": float(instructor_component),
        "room_efficiency": float(room_component),
        "course_priority": float(priority_component),
        "cluster_compactness": float(cluster_component),
        "total": float(total),
    }
