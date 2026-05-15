# OpenRent Agent

An AI-powered automation bot that replicates manual rental property workflows on the [OpenRent](https://www.openrent.co.uk) platform. It searches listings, manages landlord conversations, and generates AI-driven replies — all driven by a Python backend with Playwright browser automation.

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3, Flask, SQLAlchemy |
| Browser automation | Playwright (headless) |
| Database | PostgreSQL (async via asyncpg) |
| AI replies | OpenAI API |
| Config | python-dotenv |

## Project Structure

```
openrent-agent/
├── app/
│   ├── ai/              # AI reply generation
│   ├── browser/         # Playwright launcher, auth, selectors
│   ├── db/              # SQLAlchemy models, repository, connection
│   ├── extraction/      # Data extractors (structured data, phone numbers)
│   └── openrent/        # Platform interactions (search, inbox, messaging, listings)
├── scripts/
│   ├── process_listings.py   # Crawl and store search results
│   ├── process_replies.py    # Auto-reply to landlord messages
│   ├── run_workers.py        # Background task runner
│   ├── run_dashboard.py      # Dashboard server
│   └── seed_data.py          # Populate test data
├── tests/
└── frontend/            # React scaffold (not yet developed)
```

## Setup

### Prerequisites

- Python 3.10+
- PostgreSQL
- Node.js (for frontend, when ready)

### Install

```bash
cd openrent-agent
pip install -r requirements.txt
playwright install chromium
```

### Environment

Create a `.env` file:

```env
DATABASE_URL=postgresql+asyncpg://user:password@localhost/openrent
OPENAI_API_KEY=sk-...
OPENRENT_EMAIL=your@email.com
OPENRENT_PASSWORD=yourpassword
PROXY_URL=                  # optional
HEADLESS=true
OPENAI_REPLY_MODEL=gpt-4.1-mini
SIMULATION_DEFAULT_TEMPERATURE=0
```

### Database

```bash
python -m app.db.init_db
```

## Usage

**Search for listings:**
```bash
python scripts/process_listings.py
```

**Process and auto-reply to inbox messages:**
```bash
python scripts/process_replies.py
```

**Run background workers:**
```bash
python scripts/run_workers.py
```

**Seed test data:**
```bash
python scripts/seed_data.py
```

**Run the simulation lab CLI:**
```bash
python scripts/run_simulation_lab.py --seed 42 --max-turns 1
```

**Run the simulation lab API:**
```bash
uvicorn app.api.main:app --reload
```

**Run the Simulation Lab UI:**
```bash
cd frontend/simulation-lab
npm install
npm run dev
```

If the API is not running on `http://127.0.0.1:8000`, set:
```bash
VITE_SIMULATION_API_BASE=http://127.0.0.1:8000
```

Example output excerpt:
```text
{
  "scenario_id": "outreach-screening-before-phone",
  "start_mode": "agent_starts",
  "initial_message_source": "fixture",
  "policy_id": "production-policy-v1",
  "deterministic_seed": 42,
  "transcript": [
    {
      "speaker": "agent",
      "message": "Hi, I'm Mary, I work in IT. My husband and I really like your property and were hoping to have a quick call before booking a viewing. Could you please share your phone number?"
    },
    {
      "speaker": "actor",
      "message": "Hi, thanks for your message. Are you working at the moment and when would you be looking to move?"
    },
    {
      "speaker": "agent",
      "message": "I work full-time and can move next week. Could you share your phone number please?"
    }
  ],
  "evaluation": {
    "score": 1.0,
    "passed": true
  }
}
```

## Core Modules

- **`app/browser/`** — Initialises Playwright, handles login, CSS selectors
- **`app/openrent/`** — Search queries, inbox navigation, messaging, listing scraping, landlord extraction, popup handling
- **`app/db/`** — ORM models (`Property`, `Conversation`, `Job`), async CRUD repository
- **`app/ai/`** — Incoming message processing and OpenAI-backed reply generation
- **`app/extraction/`** — Structured data extraction from conversations; phone number parsing
- **`simulation/`** — Offline agent evaluation runtime with deterministic sessions, event logs, replay output, and JSON artifacts

## Simulation Lab

The repository now includes a separate top-level `simulation/` subsystem for offline AI evaluation. It is intentionally isolated from `app/openrent`, browser automation, workers, and the production dashboard flow.

Phase 1 is intentionally narrow:
- one deterministic scenario
- one landlord actor
- one production-like policy
- one event log as the source of truth
- one transcript projection derived from events
- one heuristic evaluator
- one replay output
- one JSON session artifact

The session artifact captures:
- raw prompt and raw completion
- token and latency metadata
- event timestamps
- projected transcript
- evaluation score and failure types

## Simulation Lab UI

`frontend/simulation-lab` is a developer-facing inspection tool for the JSON-backed simulation runs stored under `simulation/datasets/runs/`.

Current API endpoints:
- `POST /simulation/run`
- `POST /simulation/interactive/start`
- `POST /simulation/interactive/{session_id}/message`
- `GET /simulation/interactive/{session_id}`
- `GET /simulation/sessions`
- `GET /simulation/sessions/{session_id}`
- `GET /simulation/results/{session_id}`

The UI is intentionally narrow and debug-first:
- left column: run controls and session artifact list
- right column: transcript, event timeline, evaluation, runtime context, prompt/completion inspection, and replay output

There is no database persistence for the lab yet. The API reads and writes the existing JSON artifacts only.

## Simulation Modes

The lab now supports two separate modes that share the same artifact, replay, transcript, evaluation, and runtime-context plumbing:

- **Simulation Mode** — deterministic, automated actor, regression-friendly, seed/max-turn driven
- **Interactive Mode** — human-driven actor messages from the UI, live AI replies, exploratory/debugging focused

Deterministic runs remain unchanged. Interactive sessions are an additive path and are persisted to the same JSON artifact directory under `simulation/datasets/runs/` with:

```json
{
  "mode": "interactive"
}
```

Within both modes, scenarios now also support two conversation start states:

- **`actor_starts`** — landlord/persona opens first, then the AI agent replies using the reply policy
- **`agent_starts`** — the session begins with the real first-outreach pattern, where the agent sends an initial message template before the actor responds

`actor_starts` is the reply-handling path.

`agent_starts` is the first-contact outreach path.

The default production-like regression baseline is:

- `scenario_id = outreach-screening-before-phone`
- `start_mode = agent_starts`
- `initial_message_source = fixture`

Canonical scenario families:

- `outreach-screening-before-phone`
- `outreach-phone-request`
- `reply-after-landlord-question`

The initial message for `agent_starts` is provided through a simulation adapter:

- `FixtureInitialMessageProvider`
- `AccountInitialMessageProvider`
- `ManualInitialMessageProvider`

### Interactive Flow

Interactive mode keeps the same event-driven shape:

`Human actor message -> ACTOR_RESPONDED -> REPLY_GENERATED -> evaluation/runtime_context update -> artifact saved`

Human-entered actor messages still project into the transcript and replay output the same way as simulated actor messages.

For `agent_starts`, the initial outreach is emitted as:

`AGENT_INITIAL_MESSAGE_SENT`

This is intentionally distinct from `REPLY_GENERATED`, so the replay and observability views can separate fixed/template outreach from AI-generated replies.

### Running Interactive Mode

1. Start the API:

```bash
uvicorn app.api.main:app --reload
```

2. Start the Simulation Lab UI:

```bash
cd frontend/simulation-lab
npm install
npm run dev
```

3. Open the UI, switch to `Interactive Mode`, start a session, then type landlord/persona messages into the actor input box.

The UI will:
- append `ACTOR_RESPONDED`, `REPLY_GENERATED`, and evaluation events after each message
- refresh transcript and replay output
- update runtime context, prompt/completion inspection, token usage, and latency

For `agent_starts`, choose:

- a `start_mode` of `agent_starts`
- an initial message source of `fixture`, `account`, or `manual`

Default source guidance:

- `fixture` for deterministic regression testing
- `account` for targeted production-fidelity checks using the real `Account.initial_message`
- `manual` for ad hoc experiments
