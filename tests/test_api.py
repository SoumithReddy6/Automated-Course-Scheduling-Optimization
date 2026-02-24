from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.api.main import app


client = TestClient(app)


def load_sample_payload() -> dict:
    sample_path = Path(__file__).resolve().parents[1] / "data" / "sample_input.json"
    with sample_path.open("r", encoding="utf-8") as file:
        return json.load(file)


def load_csv_request_files() -> dict[str, tuple[str, bytes, str]]:
    csv_dir = Path(__file__).resolve().parents[1] / "data" / "csv"
    filenames = {
        "courses_file": "courses.csv",
        "instructors_file": "instructors.csv",
        "rooms_file": "rooms.csv",
        "time_slots_file": "time_slots.csv",
    }
    files: dict[str, tuple[str, bytes, str]] = {}
    for field, filename in filenames.items():
        file_path = csv_dir / filename
        files[field] = (filename, file_path.read_bytes(), "text/csv")
    return files


def test_generate_endpoint_returns_schedule() -> None:
    payload = load_sample_payload()
    response = client.post("/generate", params={"solver_mode": "auto"}, json=payload)

    assert response.status_code == 200
    body = response.json()

    assert body["result"]["status"] in {
        "optimal",
        "feasible",
        "fallback",
        "fallback_partial",
    }
    assert body["result"]["runtime_seconds"] >= 0
    assert body["result"]["metrics"]["sessions_required"] > 0
    assert len(body["result"]["assignments"]) > 0


def test_validate_endpoint_accepts_generated_solution() -> None:
    payload = load_sample_payload()
    generated = client.post("/generate", params={"solver_mode": "auto"}, json=payload)
    assert generated.status_code == 200

    generated_body = generated.json()
    validation_payload = {
        "data": payload,
        "assignments": generated_body["result"]["assignments"],
    }

    response = client.post("/validate", json=validation_payload)

    assert response.status_code == 200
    assert "valid" in response.json()


def test_compare_endpoint_returns_best_scenario() -> None:
    payload = load_sample_payload()
    compare_payload = {
        "data": payload,
        "scenarios": [
            {
                "name": "Balanced",
                "solver_mode": "auto",
                "options": payload["options"],
            },
            {
                "name": "Aggressive runtime",
                "solver_mode": "auto",
                "options": {
                    **payload["options"],
                    "time_limit_seconds": 5,
                },
            },
        ],
    }

    response = client.post("/compare", json=compare_payload)

    assert response.status_code == 200
    body = response.json()
    assert len(body["scenarios"]) == 2
    assert body["best_scenario"] in {"Balanced", "Aggressive runtime"}


def test_generate_csv_endpoint_returns_schedule() -> None:
    payload = load_sample_payload()
    options_json = json.dumps(payload["options"])
    response = client.post(
        "/generate/csv",
        params={"solver_mode": "auto"},
        data={"options_json": options_json},
        files=load_csv_request_files(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["result"]["status"] in {
        "optimal",
        "feasible",
        "fallback",
        "fallback_partial",
    }
    assert len(body["result"]["assignments"]) > 0


def test_compare_csv_endpoint_returns_best_scenario() -> None:
    payload = load_sample_payload()
    scenarios: list[dict[str, Any]] = [
        {
            "name": "Balanced",
            "solver_mode": "auto",
            "options": payload["options"],
        },
        {
            "name": "Fast Runtime",
            "solver_mode": "auto",
            "options": {
                **payload["options"],
                "time_limit_seconds": 5,
            },
        },
    ]

    response = client.post(
        "/compare/csv",
        data={"scenarios_json": json.dumps(scenarios)},
        files=load_csv_request_files(),
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["scenarios"]) == 2
    assert body["best_scenario"] in {"Balanced", "Fast Runtime"}
