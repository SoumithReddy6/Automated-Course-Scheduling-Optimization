from __future__ import annotations

from collections import defaultdict

from app.core.models import ScheduleAssignment, SchedulingInput, ValidationIssue, ValidationReport
from app.core.session_utils import expand_course_sessions


def validate_schedule(
    data: SchedulingInput,
    assignments: list[ScheduleAssignment],
) -> ValidationReport:
    issues: list[ValidationIssue] = []

    sessions = expand_course_sessions(data.courses)
    session_by_id = {session.session_id: session for session in sessions}
    room_by_id = {room.id: room for room in data.rooms}
    instructor_by_id = {instructor.id: instructor for instructor in data.instructors}
    slot_by_id = {slot.id: slot for slot in data.time_slots}

    seen_sessions: set[str] = set()
    room_slot_usage: dict[tuple[str, str], list[str]] = defaultdict(list)
    instructor_slot_usage: dict[tuple[str, str], list[str]] = defaultdict(list)

    for assignment in assignments:
        session = session_by_id.get(assignment.session_id)
        if session is None:
            issues.append(
                ValidationIssue(
                    code="UNKNOWN_SESSION",
                    message=f"Session '{assignment.session_id}' does not exist in input.",
                    details={"session_id": assignment.session_id},
                )
            )
            continue

        if assignment.session_id in seen_sessions:
            issues.append(
                ValidationIssue(
                    code="DUPLICATE_SESSION_ASSIGNMENT",
                    message=(
                        f"Session '{assignment.session_id}' is assigned more than once."
                    ),
                    details={"session_id": assignment.session_id},
                )
            )
            continue

        seen_sessions.add(assignment.session_id)

        if assignment.course_id != session.course_id:
            issues.append(
                ValidationIssue(
                    code="COURSE_MISMATCH",
                    message=(
                        f"Session '{assignment.session_id}' references course '{assignment.course_id}' "
                        f"but expected '{session.course_id}'."
                    ),
                    details={
                        "session_id": assignment.session_id,
                        "expected_course_id": session.course_id,
                        "provided_course_id": assignment.course_id,
                    },
                )
            )

        if assignment.instructor_id != session.instructor_id:
            issues.append(
                ValidationIssue(
                    code="INSTRUCTOR_MISMATCH",
                    message=(
                        f"Session '{assignment.session_id}' references instructor "
                        f"'{assignment.instructor_id}' but expected '{session.instructor_id}'."
                    ),
                    details={
                        "session_id": assignment.session_id,
                        "expected_instructor_id": session.instructor_id,
                        "provided_instructor_id": assignment.instructor_id,
                    },
                )
            )

        room = room_by_id.get(assignment.room_id)
        if room is None:
            issues.append(
                ValidationIssue(
                    code="UNKNOWN_ROOM",
                    message=f"Room '{assignment.room_id}' does not exist.",
                    details={"room_id": assignment.room_id},
                )
            )
        else:
            if room.capacity < session.enrollment:
                issues.append(
                    ValidationIssue(
                        code="ROOM_CAPACITY_VIOLATION",
                        message=(
                            f"Room '{room.id}' capacity {room.capacity} is lower than "
                            f"enrollment {session.enrollment} for session '{session.session_id}'."
                        ),
                        details={
                            "session_id": session.session_id,
                            "room_id": room.id,
                            "room_capacity": room.capacity,
                            "enrollment": session.enrollment,
                        },
                    )
                )

            if not set(session.required_features).issubset(set(room.features)):
                missing = sorted(set(session.required_features) - set(room.features))
                issues.append(
                    ValidationIssue(
                        code="ROOM_FEATURE_VIOLATION",
                        message=(
                            f"Room '{room.id}' does not satisfy required features for "
                            f"session '{session.session_id}'."
                        ),
                        details={
                            "session_id": session.session_id,
                            "room_id": room.id,
                            "missing_features": missing,
                        },
                    )
                )

        slot = slot_by_id.get(assignment.time_slot_id)
        if slot is None:
            issues.append(
                ValidationIssue(
                    code="UNKNOWN_TIME_SLOT",
                    message=f"Time slot '{assignment.time_slot_id}' does not exist.",
                    details={"time_slot_id": assignment.time_slot_id},
                )
            )
        else:
            instructor = instructor_by_id.get(session.instructor_id)
            if instructor is None:
                issues.append(
                    ValidationIssue(
                        code="UNKNOWN_INSTRUCTOR",
                        message=f"Instructor '{session.instructor_id}' does not exist.",
                        details={"instructor_id": session.instructor_id},
                    )
                )
            else:
                if (
                    instructor.available_time_slots
                    and slot.id not in instructor.available_time_slots
                ):
                    issues.append(
                        ValidationIssue(
                            code="INSTRUCTOR_AVAILABILITY_VIOLATION",
                            message=(
                                f"Instructor '{instructor.id}' is not available for slot '{slot.id}'."
                            ),
                            details={
                                "session_id": session.session_id,
                                "instructor_id": instructor.id,
                                "time_slot_id": slot.id,
                            },
                        )
                    )

            if session.allowed_time_slots and slot.id not in session.allowed_time_slots:
                issues.append(
                    ValidationIssue(
                        code="COURSE_TIME_WINDOW_VIOLATION",
                        message=(
                            f"Session '{session.session_id}' is outside allowed time windows "
                            f"for course '{session.course_id}'."
                        ),
                        details={
                            "session_id": session.session_id,
                            "course_id": session.course_id,
                            "time_slot_id": slot.id,
                        },
                    )
                )

        room_slot_usage[(assignment.room_id, assignment.time_slot_id)].append(
            assignment.session_id
        )
        instructor_slot_usage[(assignment.instructor_id, assignment.time_slot_id)].append(
            assignment.session_id
        )

    for (room_id, slot_id), session_ids in room_slot_usage.items():
        if len(session_ids) > 1:
            issues.append(
                ValidationIssue(
                    code="ROOM_TIME_CONFLICT",
                    message=(
                        f"Room '{room_id}' is assigned to multiple sessions at slot '{slot_id}'."
                    ),
                    details={
                        "room_id": room_id,
                        "time_slot_id": slot_id,
                        "session_ids": session_ids,
                    },
                )
            )

    for (instructor_id, slot_id), session_ids in instructor_slot_usage.items():
        if len(session_ids) > 1:
            issues.append(
                ValidationIssue(
                    code="INSTRUCTOR_TIME_CONFLICT",
                    message=(
                        f"Instructor '{instructor_id}' is assigned to multiple sessions at "
                        f"slot '{slot_id}'."
                    ),
                    details={
                        "instructor_id": instructor_id,
                        "time_slot_id": slot_id,
                        "session_ids": session_ids,
                    },
                )
            )

    missing_sessions = sorted(set(session_by_id) - seen_sessions)
    for session_id in missing_sessions:
        issues.append(
            ValidationIssue(
                code="MISSING_SESSION_ASSIGNMENT",
                message=f"Session '{session_id}' is not assigned.",
                details={"session_id": session_id},
            )
        )

    has_errors = any(issue.level == "error" for issue in issues)
    return ValidationReport(valid=not has_errors, issues=issues)
