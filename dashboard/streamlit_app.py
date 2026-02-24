from __future__ import annotations

import io
import json
import os

import pandas as pd
import requests
import streamlit as st

API_BASE_URL = os.getenv("SCHEDULER_API_BASE_URL", "http://localhost:8000")


def _csv_row_count(uploaded_file: st.runtime.uploaded_file_manager.UploadedFile | None) -> int:
    if uploaded_file is None:
        return 0
    return len(pd.read_csv(io.BytesIO(uploaded_file.getvalue())))


def _csv_request_files(
    courses_file: st.runtime.uploaded_file_manager.UploadedFile,
    instructors_file: st.runtime.uploaded_file_manager.UploadedFile,
    rooms_file: st.runtime.uploaded_file_manager.UploadedFile,
    time_slots_file: st.runtime.uploaded_file_manager.UploadedFile,
) -> dict[str, tuple[str, bytes, str]]:
    return {
        "courses_file": (courses_file.name or "courses.csv", courses_file.getvalue(), "text/csv"),
        "instructors_file": (
            instructors_file.name or "instructors.csv",
            instructors_file.getvalue(),
            "text/csv",
        ),
        "rooms_file": (rooms_file.name or "rooms.csv", rooms_file.getvalue(), "text/csv"),
        "time_slots_file": (
            time_slots_file.name or "time_slots.csv",
            time_slots_file.getvalue(),
            "text/csv",
        ),
    }


def _build_options(
    time_limit_seconds: int,
    num_workers: int,
    enable_fallback: bool,
    instructor_preference: int,
    room_efficiency: int,
    cluster_compactness: int,
    course_priority: int,
) -> dict:
    return {
        "time_limit_seconds": int(time_limit_seconds),
        "num_workers": int(num_workers),
        "enable_fallback": bool(enable_fallback),
        "objective_weights": {
            "instructor_preference": int(instructor_preference),
            "room_efficiency": int(room_efficiency),
            "cluster_compactness": int(cluster_compactness),
            "course_priority": int(course_priority),
        },
    }


st.set_page_config(page_title="Scheduling Optimizer", layout="wide")
st.title("Academic Scheduling Optimization Dashboard")

st.markdown(
    "Use JSON or CSV inputs to generate timetables, validate quality metrics, and compare scenarios."
)

with st.sidebar:
    st.header("API")
    api_base_url = st.text_input("Base URL", value=API_BASE_URL)

st.subheader("Input Source")
input_mode = st.radio("Choose input mode", ["JSON", "CSV files"], horizontal=True)

payload: dict | None = None
courses_file = None
instructors_file = None
rooms_file = None
time_slots_file = None

if input_mode == "JSON":
    uploaded_json = st.file_uploader("Upload scheduler JSON", type=["json"])
    if uploaded_json is None:
        st.info("Upload a JSON file to begin.")
        st.stop()
    payload = json.load(uploaded_json)
else:
    col_a, col_b = st.columns(2)
    with col_a:
        courses_file = st.file_uploader("Upload courses.csv", type=["csv"], key="courses_csv")
        rooms_file = st.file_uploader("Upload rooms.csv", type=["csv"], key="rooms_csv")
    with col_b:
        instructors_file = st.file_uploader(
            "Upload instructors.csv", type=["csv"], key="instructors_csv"
        )
        time_slots_file = st.file_uploader(
            "Upload time_slots.csv", type=["csv"], key="time_slots_csv"
        )

    if not all([courses_file, instructors_file, rooms_file, time_slots_file]):
        st.info("Upload all 4 CSV files to continue.")
        st.stop()

st.subheader("Input Summary")
col1, col2, col3, col4 = st.columns(4)
if input_mode == "JSON" and payload is not None:
    col1.metric("Courses", len(payload.get("courses", [])))
    col2.metric("Instructors", len(payload.get("instructors", [])))
    col3.metric("Rooms", len(payload.get("rooms", [])))
    col4.metric("Time Slots", len(payload.get("time_slots", [])))
else:
    col1.metric("Courses", _csv_row_count(courses_file))
    col2.metric("Instructors", _csv_row_count(instructors_file))
    col3.metric("Rooms", _csv_row_count(rooms_file))
    col4.metric("Time Slots", _csv_row_count(time_slots_file))

st.subheader("Solver Options")
opt_col1, opt_col2, opt_col3 = st.columns(3)
time_limit = opt_col1.number_input("Time Limit (sec)", min_value=1, value=15)
num_workers = opt_col2.number_input("Workers", min_value=1, value=8)
enable_fallback = opt_col3.checkbox("Enable fallback", value=True)

weight_col1, weight_col2, weight_col3, weight_col4 = st.columns(4)
instructor_pref_weight = weight_col1.number_input(
    "Instructor weight", min_value=0, value=5
)
room_eff_weight = weight_col2.number_input("Room efficiency weight", min_value=0, value=3)
cluster_weight = weight_col3.number_input("Cluster weight", min_value=0, value=4)
course_priority_weight = weight_col4.number_input("Priority weight", min_value=0, value=2)

selected_options = _build_options(
    time_limit_seconds=int(time_limit),
    num_workers=int(num_workers),
    enable_fallback=enable_fallback,
    instructor_preference=int(instructor_pref_weight),
    room_efficiency=int(room_eff_weight),
    cluster_compactness=int(cluster_weight),
    course_priority=int(course_priority_weight),
)

st.subheader("Generate Schedule")
mode = st.selectbox("Solver mode", ["auto", "cp_sat", "heuristic"], index=0)
if st.button("Run /generate"):
    with st.spinner("Generating..."):
        if input_mode == "JSON" and payload is not None:
            payload_with_options = {**payload, "options": selected_options}
            response = requests.post(
                f"{api_base_url}/generate",
                params={"solver_mode": mode},
                json=payload_with_options,
                timeout=120,
            )
        else:
            response = requests.post(
                f"{api_base_url}/generate/csv",
                params={"solver_mode": mode},
                files=_csv_request_files(
                    courses_file=courses_file,
                    instructors_file=instructors_file,
                    rooms_file=rooms_file,
                    time_slots_file=time_slots_file,
                ),
                data={"options_json": json.dumps(selected_options)},
                timeout=120,
            )

    if response.ok:
        body = response.json()
        result = body["result"]
        validation = body["validation"]

        st.success(
            f"Status: {result['status']} | Solver: {result['solver']} | Runtime: {result['runtime_seconds']}s"
        )
        st.write(result["metrics"])

        assignments_df = pd.DataFrame(result["assignments"])
        if not assignments_df.empty:
            st.dataframe(assignments_df, use_container_width=True)
            csv_output = assignments_df.to_csv(index=False).encode("utf-8")
            st.download_button(
                label="Download Schedule CSV",
                data=csv_output,
                file_name="schedule.csv",
                mime="text/csv",
            )

        if not validation["valid"]:
            st.warning("Validation reported issues.")
            st.json(validation)
    else:
        st.error(f"Request failed: {response.status_code}")
        st.text(response.text)

st.subheader("Compare Scenarios")
scenario_a_time = st.number_input("Scenario A time limit (sec)", min_value=1, value=15)
scenario_b_time = st.number_input("Scenario B time limit (sec)", min_value=1, value=8)

if st.button("Run /compare"):
    scenario_a_options = {**selected_options, "time_limit_seconds": int(scenario_a_time)}
    scenario_b_options = {
        **selected_options,
        "time_limit_seconds": int(scenario_b_time),
        "objective_weights": {
            "instructor_preference": max(0, int(instructor_pref_weight) - 1),
            "room_efficiency": int(room_eff_weight) + 1,
            "cluster_compactness": max(0, int(cluster_weight) - 2),
            "course_priority": max(0, int(course_priority_weight) - 1),
        },
    }

    scenarios = [
        {
            "name": "Balanced",
            "solver_mode": "auto",
            "options": scenario_a_options,
        },
        {
            "name": "Fast Runtime",
            "solver_mode": "auto",
            "options": scenario_b_options,
        },
    ]

    with st.spinner("Comparing scenarios..."):
        if input_mode == "JSON" and payload is not None:
            compare_payload = {
                "data": {**payload, "options": selected_options},
                "scenarios": scenarios,
            }
            response = requests.post(
                f"{api_base_url}/compare",
                json=compare_payload,
                timeout=180,
            )
        else:
            response = requests.post(
                f"{api_base_url}/compare/csv",
                files=_csv_request_files(
                    courses_file=courses_file,
                    instructors_file=instructors_file,
                    rooms_file=rooms_file,
                    time_slots_file=time_slots_file,
                ),
                data={
                    "options_json": json.dumps(selected_options),
                    "scenarios_json": json.dumps(scenarios),
                },
                timeout=180,
            )

    if response.ok:
        body = response.json()
        st.success(f"Best scenario: {body.get('best_scenario')}")

        rows = []
        for scenario in body["scenarios"]:
            result = scenario["result"]
            metrics = result["metrics"]
            rows.append(
                {
                    "scenario": scenario["name"],
                    "status": result["status"],
                    "solver": result["solver"],
                    "runtime_seconds": result["runtime_seconds"],
                    "objective_value": result["objective_value"],
                    "coverage_pct": metrics["coverage_pct"],
                    "room_utilization_pct": metrics["room_utilization_pct"],
                    "instructor_preference_pct": metrics["instructor_preference_pct"],
                    "hard_violations": metrics["hard_violations"],
                }
            )

        st.dataframe(pd.DataFrame(rows), use_container_width=True)
    else:
        st.error(f"Request failed: {response.status_code}")
        st.text(response.text)
