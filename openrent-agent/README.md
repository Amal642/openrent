# OpenRent Agent

OpenRent Agent is a FastAPI, Playwright, OpenAI, and React project for managing OpenRent outreach, replies, lead status, and simulation-based conversation testing.

The current development focus is the simulation lab: a separate UI for testing landlord conversations, comparing AI conversation designs, and auditing how the model progresses toward viewing coordination and phone-number capture.

## Stack

| Area | Technology |
| --- | --- |
| API | FastAPI |
| Automation | Playwright |
| Database | SQLAlchemy + SQLite/Postgres |
| AI replies | OpenAI API |
| Main dashboard | React + Vite |
| Simulation lab | React + Vite |
| Tests | pytest |

## Project Layout

```text
openrent-agent/
  app/
    ai/                         Prompt and reply generation
    api/                        FastAPI application
    browser/                    Playwright browser/session helpers
    db/                         Database models and repository
    openrent/                   OpenRent platform workflow code
  frontend/
    openrent-command-center/    Main operations dashboard
    simulation-lab/             Conversation testing and audit UI
  scripts/                      Worker and one-off operational scripts
  simulation/
    compare.py                  Compare conversation designs
    conversation_designs.py     Design metadata: names, opening messages, success/failure criteria
    conversation_state.py       Deterministic transcript state analyzer
    scenario_library.py         Reusable landlord test scenarios
    evaluators/                 Heuristic scorecards
    sessions/                   Session artifacts, store, transcript models
    templates/                  Initial-message providers
  tests/
```

## Setup

From `openrent-agent/`:

```powershell
python -m pip install -r requirements.txt
playwright install chromium
```

Create `.env` from `.env.example` and set at least:

```env
DATABASE_URL=sqlite:///openrent.db
OPENAI_API_KEY=sk-...
HEADLESS=false
AI_AUTOSEND=false
```

## Run API

From `openrent-agent/`:

```powershell
uvicorn app.api.main:app --reload --host 127.0.0.1 --port 8000
```

Useful endpoints:

```text
GET  /api/health
GET  /simulation/conversation-designs
GET  /simulation/scenarios
POST /simulation/compare-designs
POST /simulation/interactive/start
POST /simulation/interactive/{session_id}/message
```

## Run Simulation Lab

From `openrent-agent/frontend/simulation-lab/`:

```powershell
npm install
npm run dev
```

Open the Vite URL, usually:

```text
http://127.0.0.1:5173
```

The simulation lab supports:

- Audit mode for client/tester-facing transcript review.
- Dev mode for internal logs, prompts, completions, runtime context, and event timelines.
- Interactive sessions where the AI starts as the renter and testers reply as the landlord.
- Conversation design selection, including `viewing_first_v1` and `phone_first_v1`.
- Compare mode for running the same landlord scenario against multiple AI designs.
- Conversation state tracking for viewing progress, screening, coordination, early phone asks, refusals, and stalls.

## Conversation Design Testing

**AI reply behavior** (the rules that control how the AI responds during a conversation) lives exclusively in:

```text
app/ai/prompts.py  →  _DESIGN_RULES dict
```

Each conversation design has its reply rules embedded there, keyed by design ID. This is the single source of truth for AI behavior in the simulation lab.

**Conversation design metadata** (names, opening messages, success/failure criteria) lives in:

```text
simulation/conversation_designs.py
```

This file defines what each design is called and how sessions start — it does not control how the AI replies.

Static landlord scenarios live in:

```text
simulation/scenario_library.py
```

Current seeded scenarios:

- `normal_viewing_offer`
- `screening_before_viewing`
- `phone_refusal_before_viewing`
- `asks_for_tenant_phone_early`
- `vague_landlord_reply`
- `viewing_confirmed_then_coordination`

The current preferred strategy is `viewing_first_v1`:

- Move toward arranging a viewing first.
- Answer screening questions naturally and briefly.
- Do not ask for phone before viewing progress.
- Ask for phone only when coordination is reasonable.
- Sound like a real person texting — never robotic or scripted.

## Run Main Dashboard

From `openrent-agent/frontend/openrent-command-center/`:

```powershell
npm install
npm run dev
```

For production serving, build the dashboard and run the FastAPI app:

```powershell
npm run build
cd ..\..
uvicorn app.api.main:app --reload --host 127.0.0.1 --port 8000
```

## Run Workers

From `openrent-agent/`:

```powershell
python scripts\run_workers.py
```

One-off scripts:

```powershell
python scripts\process_listings.py
python scripts\process_replies.py
python scripts\process_viewing_reminders.py
```

## Tests

Backend simulation/API tests:

```powershell
pytest openrent-agent/tests/simulation openrent-agent/tests/test_simulation_api.py openrent-agent/tests/test_prompt_persona_flow.py
```

Simulation lab build:

```powershell
cd openrent-agent/frontend/simulation-lab
npm run build
```

Main dashboard build:

```powershell
cd openrent-agent/frontend/openrent-command-center
npm run build
```

## Notes

- The simulation lab is intentionally separate from the main operations dashboard.
- Generated simulation run artifacts and frontend dependency folders should not be committed.
- Testers are currently treated as trusted users, so the lab can show shared session history.
- Dev mode may expose prompts, completions, event logs, and runtime context. Use audit mode for client-facing testing.
