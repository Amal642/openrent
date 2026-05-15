# Non-Simulation Code Changes

This file documents changes made outside the isolated simulation/UI implementation.

## `app/api/main.py`

Added Simulation Lab API routes to the existing FastAPI app:

- `POST /simulation/run`
- `GET /simulation/sessions`
- `GET /simulation/sessions/{session_id}`
- `GET /simulation/results/{session_id}`

Also changed database repository imports from module-level imports to lazy request-time imports through `_repository()`.

Reason: the Simulation Lab API should be able to start and serve JSON-backed simulation endpoints without requiring database setup at import time.

Existing `/api/*` routes remain in place.

## `requirements.txt`

Added:

- `fastapi`
- `uvicorn`
- `openai`

Reason: the existing API file uses FastAPI, the README now documents running it with Uvicorn, and the simulation runner uses the OpenAI client through the existing reply generation path.

## `pyproject.toml`

Added project dependencies:

- `fastapi`
- `uvicorn`
- `openai`

Added pytest config:

- `pythonpath = ["."]`
- `testpaths = ["tests"]`

Reason: tests should import local packages consistently from the repo root and avoid collecting helper scripts under `scripts/test_*.py`.

## `README.md`

Added instructions for running:

- the Simulation Lab API
- the Simulation Lab UI

Reason: developers need the commands for starting the new debug UI and pointing it at the API.
