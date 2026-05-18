# OpenRent Agent

OpenRent Agent automates the OpenRent workflow with Playwright browser control, a FastAPI backend, OpenAI-generated messaging, and a React command center for operations.

## Stack

| Layer | Technology |
|---|---|
| API + dashboard serving | FastAPI |
| Browser automation | Playwright |
| Database | SQLAlchemy |
| AI messaging | OpenAI API |
| Frontend | React + Vite |
| Config | python-dotenv |

## Project Layout

```text
openrent-agent/
├── app/
│   ├── ai/                # prompts, personas, reply generation
│   ├── api/               # FastAPI app
│   ├── browser/           # Playwright launch + login
│   ├── db/                # models, repository, init_db
│   ├── dashboard/         # legacy Flask/Jinja dashboard
│   └── openrent/          # platform interactions
├── frontend/
│   └── openrent-command-center/   # React/Vite command center
├── scripts/
│   ├── process_listings.py
│   ├── process_replies.py
│   ├── process_viewing_reminders.py
│   ├── run_workers.py
│   └── run_dashboard.py   # legacy Flask entrypoint
└── tests/
```

## Prerequisites

- Python 3.11+
- Node.js 18+
- An OpenAI API key
- Chromium installed through Playwright

## Install

```powershell
cd openrent-agent
python -m pip install -r requirements.txt
python -m pip install sqlalchemy fastapi uvicorn playwright
playwright install chromium
```

## Environment

Create `.env` in `openrent-agent/`.

Minimum local setup:

```env
DATABASE_URL=sqlite:///openrent.db
OPENAI_API_KEY=sk-...
HEADLESS=false
AI_AUTOSEND=false
WORKER_TICK_SECONDS=300
```

Notes:

- `DATABASE_URL` can be SQLite for local use or Postgres for production.
- `HEADLESS=false` is recommended while testing Playwright flows.
- `AI_AUTOSEND=false` is recommended while validating prompts and reply behavior.

## Running

### 1. Start the API and dashboard

From `openrent-agent/`:

```powershell
uvicorn app.api.main:app --reload --host 127.0.0.1 --port 8000
```

Open:

```text
http://127.0.0.1:8000
```

This serves the built React command center from `frontend/openrent-command-center/dist`.

### 2. Run the React app in dev mode

If you want live frontend development instead of serving the built files:

```powershell
cd frontend\openrent-command-center
npm install
npm run dev
```

Then open the Vite URL, usually:

```text
http://127.0.0.1:5174
```

The Vite dev server proxies `/api` to `http://127.0.0.1:8000`.

### 3. Run the workers

In another terminal:

```powershell
cd openrent-agent
python scripts\run_workers.py
```

This runs per-account workers for:

- listing processing
- reply processing
- viewing reminder cancellations

### 4. Run one-off scripts

```powershell
python scripts\process_listings.py
python scripts\process_replies.py
python scripts\process_viewing_reminders.py
```

## Database

The FastAPI app initializes the schema on startup automatically.

If you want to initialize it manually:

```powershell
python -m app.db.init_db
```

## Testing

Run the focused tests added for the current command center and prompt flow:

```powershell
pytest -q tests\test_prompt_persona_flow.py tests\test_api_command_center.py
```

Build the frontend:

```powershell
cd frontend\openrent-command-center
npm run build
```

## Current UI

The React command center includes:

- Accounts
  - create
  - edit
  - delete
  - toggle active
  - run account
- Search Profiles
  - create
  - edit
  - deactivate
- Leads
  - filter by status
  - mark complete
  - mark skipped
- Metrics
  - summary cards
  - 14-day chart
- Logs
  - recent operational log stream

## Important Notes

- `app/dashboard/` and `scripts/run_dashboard.py` are legacy Flask/Jinja dashboard code. The primary UI is now the FastAPI-served React command center.
- The API expects valid OpenRent account records in the database before the workers can do useful work.
- The frontend folder `frontend/openrent-command-center` is currently tracked oddly in git in the parent repo. That does not block local running, but it may affect committing from the parent repository until the git metadata is cleaned up.
