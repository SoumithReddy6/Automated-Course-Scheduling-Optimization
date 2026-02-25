# AI-Based Academic Scheduling Optimization Platform
[![Live Demo](https://img.shields.io/badge/Streamlit-Live%20Demo-brightgreen?logo=streamlit)](https://automated-course-scheduling-optimization-escsohedmmlugagb6whus.streamlit.app)
Production-style academic timetable optimization platform using Google OR-Tools CP-SAT, FastAPI, and optional Streamlit UI.

## What This Project Includes

- CP-SAT scheduler for conflict-free timetable generation.
- 10+ modeled constraints (capacity, availability, room-time collisions, instructor-time collisions, feature matching, same-day spacing, max sessions/day, etc.).
- Hard + soft constraints with weighted multi-objective scoring.
- Fallback heuristic solver for large-scale overload scenarios.
- FastAPI service with:
  - `POST /generate`
  - `POST /generate/csv`
  - `POST /validate`
  - `POST /compare`
  - `POST /compare/csv`
- Optional Streamlit dashboard for simulation and schedule export.
- Dockerized deployment layout for EC2/Render-style hosting.
- Structured logging + automated validation checks on each generation run.

## Architecture

### Core Engine (`/app/core`)

- `solver.py`: CP-SAT optimizer + fallback routing logic.
- `heuristic.py`: greedy fallback when CP-SAT is infeasible/unknown/time-bound.
- `validation.py`: hard-constraint validation and issue reporting.
- `objective.py`: weighted objective scoring (instructor preference, room efficiency, clustering, priority).
- `metrics.py`: runtime and quality metrics.

### API Layer (`/app/api/main.py`)

- `/generate`: build a schedule from input model and solver settings.
- `/generate/csv`: build a schedule from `courses.csv`, `instructors.csv`, `rooms.csv`, `time_slots.csv`.
- `/validate`: validate a provided schedule against constraints.
- `/compare`: evaluate multiple solver/weight scenarios and pick the best.
- `/compare/csv`: scenario comparison using uploaded CSV files plus `scenarios_json`.

### UI (`/dashboard/streamlit_app.py`)

- Upload JSON or CSV input.
- Run generation and scenario comparisons.
- Download resulting schedule as CSV.

### Deployment

- `Dockerfile`: API image.
- `docker-compose.yml`: API + Streamlit dashboard.

## Data Model

Input payload contains:

- `courses`
- `instructors`
- `rooms`
- `time_slots`
- `options` (time limit, workers, fallback toggle, objective weights)

A complete example is available at:

- `data/sample_input.json`
- `data/csv/`

### CSV Schema

`courses.csv`
- `id,name,instructor_id,enrollment,sessions_per_week,required_features,preferred_time_slots,allowed_time_slots,cluster_tag,priority,avoid_same_day_sessions`

`instructors.csv`
- `id,name,available_time_slots,preferred_time_slots,max_sessions_per_day`

`rooms.csv`
- `id,name,capacity,features`

`time_slots.csv`
- `id,day,start,end,order`

For list columns (for example `required_features`, `preferred_time_slots`), use `|` separators, such as `projector|lab`.

## Quick Start

### 1. Install dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
