from __future__ import annotations

from app.core.models import (
    ScheduleAssignment,
    ScheduleMetrics,
    SchedulingInput,
    ValidationReport,
)
from app.core.session_utils import expand_course_sessions


def build_metrics(
    data: SchedulingInput,
    assignments: list[ScheduleAssignment],
    validation: ValidationReport,
    objective_breakdown: dict[str, float],
) -> ScheduleMetrics:
    sessions = expand_course_sessions(data.courses)
    session_by_id = {session.session_id: session for session in sessions}
    room_by_id = {room.id: room for room in data.rooms}
    instructor_by_id = {instructor.id: instructor for instructor in data.instructors}

    sessions_required = len(sessions)
    sessions_scheduled = len(assignments)
    coverage_pct = (
        (sessions_scheduled / sessions_required) * 100.0 if sessions_required else 0.0
    )

    utilization_sum = 0.0
    utilization_count = 0
    preference_hits = 0

    for assignment in assignments:
        session = session_by_id.get(assignment.session_id)
        room = room_by_id.get(assignment.room_id)
        instructor = instructor_by_id.get(assignment.instructor_id)
        if session and room and room.capacity > 0:
            utilization_sum += session.enrollment / room.capacity
            utilization_count += 1
        if (
            instructor
            and instructor.preferred_time_slots
            and assignment.time_slot_id in instructor.preferred_time_slots
        ):
            preference_hits += 1

    room_utilization_pct = (
        (utilization_sum / utilization_count) * 100.0 if utilization_count else 0.0
    )
    instructor_preference_pct = (
        (preference_hits / sessions_scheduled) * 100.0 if sessions_scheduled else 0.0
    )

    hard_violations = sum(1 for issue in validation.issues if issue.level == "error")

    return ScheduleMetrics(
        sessions_required=sessions_required,
        sessions_scheduled=sessions_scheduled,
        coverage_pct=round(coverage_pct, 2),
        room_utilization_pct=round(room_utilization_pct, 2),
        instructor_preference_pct=round(instructor_preference_pct, 2),
        hard_violations=hard_violations,
        objective_breakdown=objective_breakdown,
    )
