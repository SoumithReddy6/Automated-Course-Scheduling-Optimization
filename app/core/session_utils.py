from __future__ import annotations

from dataclasses import dataclass

from app.core.models import Course


@dataclass(frozen=True)
class CourseSession:
    session_id: str
    course_id: str
    instructor_id: str
    enrollment: int
    priority: int
    cluster_tag: str | None
    required_features: tuple[str, ...]
    preferred_time_slots: tuple[str, ...]
    allowed_time_slots: tuple[str, ...]
    avoid_same_day_sessions: bool


def expand_course_sessions(courses: list[Course]) -> list[CourseSession]:
    sessions: list[CourseSession] = []
    for course in courses:
        for index in range(1, course.sessions_per_week + 1):
            sessions.append(
                CourseSession(
                    session_id=f"{course.id}::S{index}",
                    course_id=course.id,
                    instructor_id=course.instructor_id,
                    enrollment=course.enrollment,
                    priority=course.priority,
                    cluster_tag=course.cluster_tag,
                    required_features=tuple(course.required_features),
                    preferred_time_slots=tuple(course.preferred_time_slots),
                    allowed_time_slots=tuple(course.allowed_time_slots),
                    avoid_same_day_sessions=course.avoid_same_day_sessions,
                )
            )
    return sessions
