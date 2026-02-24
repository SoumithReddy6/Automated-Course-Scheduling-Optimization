from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class TimeSlot(BaseModel):
    id: str = Field(..., description="Unique time slot id")
    day: Literal["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    start: str = Field(..., description="Start time, e.g. 09:00")
    end: str = Field(..., description="End time, e.g. 10:15")
    order: int = Field(..., ge=0, description="Ordering index within a week")


class Room(BaseModel):
    id: str
    name: str
    capacity: int = Field(..., ge=1)
    features: list[str] = Field(default_factory=list)


class Instructor(BaseModel):
    id: str
    name: str
    available_time_slots: list[str] = Field(
        default_factory=list,
        description="If empty, instructor is assumed available for all slots",
    )
    preferred_time_slots: list[str] = Field(default_factory=list)
    max_sessions_per_day: int | None = Field(default=None, ge=1)


class Course(BaseModel):
    id: str
    name: str
    instructor_id: str
    enrollment: int = Field(..., ge=1)
    sessions_per_week: int = Field(default=1, ge=1)
    required_features: list[str] = Field(default_factory=list)
    preferred_time_slots: list[str] = Field(default_factory=list)
    allowed_time_slots: list[str] = Field(
        default_factory=list,
        description="If empty, all time slots are allowed",
    )
    cluster_tag: str | None = Field(
        default=None,
        description="Courses sharing a cluster tag are softly encouraged to stay compact",
    )
    priority: int = Field(default=5, ge=1, le=10)
    avoid_same_day_sessions: bool = True


class ObjectiveWeights(BaseModel):
    instructor_preference: int = Field(default=5, ge=0)
    room_efficiency: int = Field(default=3, ge=0)
    cluster_compactness: int = Field(default=4, ge=0)
    course_priority: int = Field(default=2, ge=0)


class SolverOptions(BaseModel):
    time_limit_seconds: int = Field(default=15, ge=1)
    num_workers: int = Field(default=8, ge=1)
    enable_fallback: bool = True
    objective_weights: ObjectiveWeights = Field(default_factory=ObjectiveWeights)


class SchedulingInput(BaseModel):
    courses: list[Course]
    instructors: list[Instructor]
    rooms: list[Room]
    time_slots: list[TimeSlot]
    options: SolverOptions = Field(default_factory=SolverOptions)


class ScheduleAssignment(BaseModel):
    session_id: str
    course_id: str
    instructor_id: str
    room_id: str
    time_slot_id: str


class ValidationIssue(BaseModel):
    code: str
    level: Literal["error", "warning"] = "error"
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ValidationReport(BaseModel):
    valid: bool
    issues: list[ValidationIssue] = Field(default_factory=list)


class ScheduleMetrics(BaseModel):
    sessions_required: int
    sessions_scheduled: int
    coverage_pct: float
    room_utilization_pct: float
    instructor_preference_pct: float
    hard_violations: int
    objective_breakdown: dict[str, float] = Field(default_factory=dict)


class ScheduleResult(BaseModel):
    status: Literal[
        "optimal",
        "feasible",
        "infeasible",
        "unknown",
        "model_invalid",
        "fallback",
        "fallback_partial",
    ]
    solver: Literal["cp_sat", "heuristic"]
    runtime_seconds: float
    objective_value: float
    assignments: list[ScheduleAssignment] = Field(default_factory=list)
    metrics: ScheduleMetrics
    notes: list[str] = Field(default_factory=list)


class GenerateResponse(BaseModel):
    result: ScheduleResult
    validation: ValidationReport


class ValidationRequest(BaseModel):
    data: SchedulingInput
    assignments: list[ScheduleAssignment]


class ScenarioConfig(BaseModel):
    name: str
    options: SolverOptions = Field(default_factory=SolverOptions)
    solver_mode: Literal["auto", "cp_sat", "heuristic"] = "auto"


class CompareRequest(BaseModel):
    data: SchedulingInput
    scenarios: list[ScenarioConfig]


class ScenarioResult(BaseModel):
    name: str
    result: ScheduleResult
    validation: ValidationReport


class CompareResponse(BaseModel):
    scenarios: list[ScenarioResult]
    best_scenario: str | None = None
