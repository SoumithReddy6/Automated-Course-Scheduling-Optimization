from __future__ import annotations

import json
import logging
from typing import Annotated

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from pydantic import ValidationError

from app.core.csv_ingestion import (
    CsvIngestionError,
    load_scheduling_input_from_csv_bytes,
    parse_scenarios_json,
)
from app.core.models import (
    CompareRequest,
    CompareResponse,
    GenerateResponse,
    ScenarioResult,
    SchedulingInput,
    ValidationRequest,
    ValidationReport,
)
from app.core.solver import SolverMode, solve_schedule
from app.core.validation import validate_schedule
from app.utils.logging import configure_logging

configure_logging()
logger = logging.getLogger(__name__)

app = FastAPI(
    title="AI Academic Scheduling Optimization Platform",
    description=(
        "Constraint-based academic scheduler using Google OR-Tools CP-SAT with "
        "automatic heuristic fallback for overload scenarios."
    ),
    version="1.0.0",
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/generate", response_model=GenerateResponse)
def generate_schedule(
    payload: SchedulingInput,
    solver_mode: Annotated[SolverMode, Query(description="auto | cp_sat | heuristic")] = "auto",
) -> GenerateResponse:
    result, validation = solve_schedule(payload, solver_mode=solver_mode)
    logger.info(
        "Generated schedule status=%s solver=%s assignments=%d runtime=%.3fs",
        result.status,
        result.solver,
        len(result.assignments),
        result.runtime_seconds,
    )
    if not validation.valid:
        logger.warning(
            "Schedule validation returned %d issue(s)",
            len(validation.issues),
        )

    return GenerateResponse(result=result, validation=validation)


@app.post("/generate/csv", response_model=GenerateResponse)
async def generate_schedule_from_csv(
    courses_file: UploadFile = File(...),
    instructors_file: UploadFile = File(...),
    rooms_file: UploadFile = File(...),
    time_slots_file: UploadFile = File(...),
    options_json: str | None = Form(default=None),
    solver_mode: Annotated[SolverMode, Query(description="auto | cp_sat | heuristic")] = "auto",
) -> GenerateResponse:
    try:
        payload = load_scheduling_input_from_csv_bytes(
            courses_csv=await courses_file.read(),
            instructors_csv=await instructors_file.read(),
            rooms_csv=await rooms_file.read(),
            time_slots_csv=await time_slots_file.read(),
            options_json=options_json,
        )
    except CsvIngestionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc

    return generate_schedule(payload=payload, solver_mode=solver_mode)


@app.post("/validate", response_model=ValidationReport)
def validate(payload: ValidationRequest) -> ValidationReport:
    report = validate_schedule(payload.data, payload.assignments)
    logger.info(
        "Validation complete valid=%s issues=%d",
        report.valid,
        len(report.issues),
    )
    return report


@app.post("/compare", response_model=CompareResponse)
def compare(payload: CompareRequest) -> CompareResponse:
    scenario_results: list[ScenarioResult] = []

    for scenario in payload.scenarios:
        scenario_input = payload.data.model_copy(deep=True)
        scenario_input.options = scenario.options
        result, validation = solve_schedule(
            scenario_input,
            solver_mode=scenario.solver_mode,
        )

        scenario_results.append(
            ScenarioResult(
                name=scenario.name,
                result=result,
                validation=validation,
            )
        )

    best_scenario: str | None = None
    if scenario_results:
        ranked = sorted(
            scenario_results,
            key=lambda item: (
                item.result.metrics.hard_violations,
                -item.result.objective_value,
                -item.result.metrics.coverage_pct,
            ),
        )
        best_scenario = ranked[0].name

    logger.info(
        "Scenario comparison complete scenarios=%d best=%s",
        len(scenario_results),
        best_scenario,
    )

    return CompareResponse(scenarios=scenario_results, best_scenario=best_scenario)


@app.post("/compare/csv", response_model=CompareResponse)
async def compare_from_csv(
    courses_file: UploadFile = File(...),
    instructors_file: UploadFile = File(...),
    rooms_file: UploadFile = File(...),
    time_slots_file: UploadFile = File(...),
    scenarios_json: str = Form(...),
    options_json: str | None = Form(default=None),
) -> CompareResponse:
    try:
        payload = load_scheduling_input_from_csv_bytes(
            courses_csv=await courses_file.read(),
            instructors_csv=await instructors_file.read(),
            rooms_csv=await rooms_file.read(),
            time_slots_csv=await time_slots_file.read(),
            options_json=options_json,
        )
        scenario_rows = parse_scenarios_json(scenarios_json)
        compare_payload = CompareRequest.model_validate(
            {"data": payload.model_dump(), "scenarios": scenario_rows}
        )
    except CsvIngestionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (ValidationError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return compare(compare_payload)
