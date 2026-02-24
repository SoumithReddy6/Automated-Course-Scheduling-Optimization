from __future__ import annotations

import csv
import io
import json
from typing import Any

from pydantic import ValidationError

from app.core.models import (
    Course,
    Instructor,
    ObjectiveWeights,
    Room,
    SchedulingInput,
    SolverOptions,
    TimeSlot,
)

TRUE_VALUES = {"1", "true", "t", "yes", "y"}
FALSE_VALUES = {"0", "false", "f", "no", "n", ""}


class CsvIngestionError(ValueError):
    pass


def _normalize_row(row: dict[str, Any]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for key, value in row.items():
        if key is None:
            continue
        normalized[key.strip()] = ("" if value is None else str(value).strip())
    return normalized


def _read_csv_bytes(file_bytes: bytes, label: str) -> list[dict[str, str]]:
    if not file_bytes:
        raise CsvIngestionError(f"{label} is empty.")

    decoded = file_bytes.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(decoded))

    if not reader.fieldnames:
        raise CsvIngestionError(f"{label} is missing a header row.")

    return [_normalize_row(row) for row in reader]


def _parse_int(value: str, field: str, row_num: int, label: str, default: int) -> int:
    if value == "":
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise CsvIngestionError(
            f"Invalid integer in {label} row {row_num} for '{field}': '{value}'."
        ) from exc


def _parse_optional_int(
    value: str,
    field: str,
    row_num: int,
    label: str,
) -> int | None:
    if value == "":
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise CsvIngestionError(
            f"Invalid integer in {label} row {row_num} for '{field}': '{value}'."
        ) from exc


def _parse_bool(
    value: str,
    field: str,
    row_num: int,
    label: str,
    default: bool,
) -> bool:
    if value == "":
        return default

    normalized = value.strip().lower()
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False

    raise CsvIngestionError(
        f"Invalid boolean in {label} row {row_num} for '{field}': '{value}'."
    )


def _parse_list(value: str) -> list[str]:
    if not value:
        return []

    delimiter = "|"
    if "|" in value:
        delimiter = "|"
    elif ";" in value:
        delimiter = ";"
    elif "," in value:
        delimiter = ","

    return [item.strip() for item in value.split(delimiter) if item.strip()]


def _required(
    row: dict[str, str],
    field: str,
    row_num: int,
    label: str,
) -> str:
    value = row.get(field, "").strip()
    if value == "":
        raise CsvIngestionError(
            f"Missing required value in {label} row {row_num}: '{field}'."
        )
    return value


def _build_courses(rows: list[dict[str, str]]) -> list[Course]:
    courses: list[Course] = []
    for idx, row in enumerate(rows, start=2):
        courses.append(
            Course(
                id=_required(row, "id", idx, "courses.csv"),
                name=_required(row, "name", idx, "courses.csv"),
                instructor_id=_required(row, "instructor_id", idx, "courses.csv"),
                enrollment=_parse_int(
                    row.get("enrollment", ""),
                    "enrollment",
                    idx,
                    "courses.csv",
                    0,
                ),
                sessions_per_week=_parse_int(
                    row.get("sessions_per_week", ""),
                    "sessions_per_week",
                    idx,
                    "courses.csv",
                    1,
                ),
                required_features=_parse_list(row.get("required_features", "")),
                preferred_time_slots=_parse_list(
                    row.get("preferred_time_slots", "")
                ),
                allowed_time_slots=_parse_list(row.get("allowed_time_slots", "")),
                cluster_tag=row.get("cluster_tag", "") or None,
                priority=_parse_int(
                    row.get("priority", ""),
                    "priority",
                    idx,
                    "courses.csv",
                    5,
                ),
                avoid_same_day_sessions=_parse_bool(
                    row.get("avoid_same_day_sessions", ""),
                    "avoid_same_day_sessions",
                    idx,
                    "courses.csv",
                    True,
                ),
            )
        )
    return courses


def _build_instructors(rows: list[dict[str, str]]) -> list[Instructor]:
    instructors: list[Instructor] = []
    for idx, row in enumerate(rows, start=2):
        instructors.append(
            Instructor(
                id=_required(row, "id", idx, "instructors.csv"),
                name=_required(row, "name", idx, "instructors.csv"),
                available_time_slots=_parse_list(
                    row.get("available_time_slots", "")
                ),
                preferred_time_slots=_parse_list(
                    row.get("preferred_time_slots", "")
                ),
                max_sessions_per_day=_parse_optional_int(
                    row.get("max_sessions_per_day", ""),
                    "max_sessions_per_day",
                    idx,
                    "instructors.csv",
                ),
            )
        )
    return instructors


def _build_rooms(rows: list[dict[str, str]]) -> list[Room]:
    rooms: list[Room] = []
    for idx, row in enumerate(rows, start=2):
        rooms.append(
            Room(
                id=_required(row, "id", idx, "rooms.csv"),
                name=_required(row, "name", idx, "rooms.csv"),
                capacity=_parse_int(
                    row.get("capacity", ""),
                    "capacity",
                    idx,
                    "rooms.csv",
                    0,
                ),
                features=_parse_list(row.get("features", "")),
            )
        )
    return rooms


def _build_time_slots(rows: list[dict[str, str]]) -> list[TimeSlot]:
    time_slots: list[TimeSlot] = []
    for idx, row in enumerate(rows, start=2):
        time_slots.append(
            TimeSlot(
                id=_required(row, "id", idx, "time_slots.csv"),
                day=_required(row, "day", idx, "time_slots.csv"),
                start=_required(row, "start", idx, "time_slots.csv"),
                end=_required(row, "end", idx, "time_slots.csv"),
                order=_parse_int(
                    row.get("order", ""),
                    "order",
                    idx,
                    "time_slots.csv",
                    0,
                ),
            )
        )
    return time_slots


def _parse_options(options_json: str | None) -> SolverOptions:
    if options_json is None or options_json.strip() == "":
        return SolverOptions()

    try:
        raw = json.loads(options_json)
    except json.JSONDecodeError as exc:
        raise CsvIngestionError("Invalid options_json payload.") from exc

    try:
        if isinstance(raw, dict):
            return SolverOptions.model_validate(raw)
        raise CsvIngestionError("options_json must be a JSON object.")
    except ValidationError as exc:
        raise CsvIngestionError(f"options_json validation failed: {exc}") from exc


def parse_scenarios_json(scenarios_json: str) -> list[dict[str, Any]]:
    try:
        raw = json.loads(scenarios_json)
    except json.JSONDecodeError as exc:
        raise CsvIngestionError("Invalid scenarios_json payload.") from exc

    if not isinstance(raw, list) or not raw:
        raise CsvIngestionError("scenarios_json must be a non-empty JSON array.")

    return raw


def load_scheduling_input_from_csv_bytes(
    *,
    courses_csv: bytes,
    instructors_csv: bytes,
    rooms_csv: bytes,
    time_slots_csv: bytes,
    options_json: str | None = None,
) -> SchedulingInput:
    courses_rows = _read_csv_bytes(courses_csv, "courses.csv")
    instructors_rows = _read_csv_bytes(instructors_csv, "instructors.csv")
    rooms_rows = _read_csv_bytes(rooms_csv, "rooms.csv")
    time_slots_rows = _read_csv_bytes(time_slots_csv, "time_slots.csv")

    if not courses_rows:
        raise CsvIngestionError("courses.csv has no data rows.")
    if not instructors_rows:
        raise CsvIngestionError("instructors.csv has no data rows.")
    if not rooms_rows:
        raise CsvIngestionError("rooms.csv has no data rows.")
    if not time_slots_rows:
        raise CsvIngestionError("time_slots.csv has no data rows.")

    options = _parse_options(options_json)

    return SchedulingInput(
        courses=_build_courses(courses_rows),
        instructors=_build_instructors(instructors_rows),
        rooms=_build_rooms(rooms_rows),
        time_slots=_build_time_slots(time_slots_rows),
        options=options,
    )
