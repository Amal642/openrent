# OpenRent Agent infra

OpenRent Agent is a FastAPI, Playwright, OpenAI, and React project for managing OpenRent outreach, replies, lead status, and simulation-based conversation testing.

The current development focus is the simulation lab: a separate, client-facing UI for testing landlord conversations, comparing AI message styles, and checking how the model progresses toward viewing coordination and phone-number capture.

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
    simulation-lab/             Client-facing conversation test UI
  scripts/                      Worker and one-off operational scripts
  simulation/
    compare.py                  Compare conversation designs
    conversation_designs.py     Design metadata, property-aware openers, personas, success/failure criteria
    conversation_state.py       Deterministic transcript state analyzer
    scenario_library.py         Reusable landlord test scenarios
    scenarios/                  Generated run/interactive scenario definitions
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
CRM_USERNAME=admin
CRM_PASSWORD_HASH=<generated-password-hash>
CRM_AUTH_SECRET=<long-random-secret>
OPENAI_API_KEY=sk-...
HEADLESS=false
AI_AUTOSEND=false
```

### Google Sheets lead export

The export is disabled by default. Configure it only with a replacement
service-account key that has not been shared in chat or committed to Git:

```env
GOOGLE_SHEETS_ENABLED=false
GOOGLE_SHEET_ID=<spreadsheet-id-between-/d/-and-/edit>
GOOGLE_SHEET_PERSON=Becky
GOOGLE_APPLICATION_CREDENTIALS=C:/Users/anees/.secrets/landroyal-sheets.json
```

Keep the JSON file outside this repository. Production platforms may store the
complete JSON in the `GOOGLE_SERVICE_ACCOUNT_JSON` secret instead of mounting a
file.

Run the read-only audit before enabling writes:

```powershell
python scripts\audit_google_sheet.py
```

The audit reports monthly tabs, header compatibility, lead-row cadence, and
whether the Person dropdown accepts `Becky`. Once the audit is clean:

```env
GOOGLE_SHEETS_ENABLED=true
```

Restart the API and RQ workers. RQ workers consume the `integrations` queue
before the browser `workers` queue:

```powershell
python rq_worker_entry.py
```

Operational endpoints:

```text
GET  /api/google-sheet/exports
GET  /api/google-sheet/exports?status=FAILED
POST /api/google-sheet/exports/{export_id}/retry
```

Existing phone leads are never backfilled implicitly. Preview them first:

```powershell
python scripts\backfill_google_sheet_exports.py
```

Create pending export records only after reviewing the preview:

```powershell
python scripts\backfill_google_sheet_exports.py --apply
```

Structured log events use the prefixes `LISTING_METADATA_`,
`GOOGLE_SHEETS_OUTBOX_`, and `GOOGLE_SHEETS_`.

Generate the CRM password hash and signing secret without storing the plain-text
password in `.env`:

```powershell
python -c "from werkzeug.security import generate_password_hash; print(generate_password_hash('replace-with-password'))"
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Set the same `CRM_USERNAME`, `CRM_PASSWORD_HASH`, and `CRM_AUTH_SECRET` values in
the API deployment environment. The Vercel dashboard only needs
`VITE_API_BASE_URL`; credentials and the signing secret must never be configured
as Vercel frontend variables.

CRM sessions last seven days. To change the password, generate a new hash and
restart the API. To immediately invalidate every active CRM session, rotate
`CRM_AUTH_SECRET` and restart the API. If access is lost, update all three CRM
environment variables directly in the API hosting provider and redeploy.

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

- Test mode for client/tester-facing conversation testing.
- Advanced mode for internal logs, prompts, completions, runtime context, and event timelines.
- Interactive sessions where the AI starts as the renter and testers reply as the landlord.
- Persona- and property-driven opening messages: the AI introduces itself with active persona details and references the scenario property through `{property_phrase}`.
- Conversation design selection across the five active message styles.
- Compare mode for running the same landlord scenario against multiple AI message styles.
- Conversation state tracking for viewing progress, screening, coordination, early phone asks, refusals, and stalls.

## Conversation Design Testing

**AI reply behavior** lives exclusively in:

```text
app/ai/prompts.py -> _DESIGN_RULES dict
```

Each active conversation design has its reply rules embedded there, keyed by design ID. This is the single source of truth for AI reply behavior in the simulation lab.

**Conversation design metadata** lives in:

```text
simulation/conversation_designs.py
```

This file owns design names, opening message templates, property-aware phrasing, simulation persona construction, and success/failure criteria. It does not control turn-by-turn AI reply behavior.

Opening messages are template strings rendered at runtime from the active persona and scenario property. The persona supplies the tenant name, partner name, and household type. The property supplies `{property_phrase}`, such as `the 2-bed in Hackney`. To change opening wording, edit `opening_message` in `conversation_designs.py`. To change who the AI is, change the scenario persona or persona template.

**Personas** live in:

```text
app/ai/personas.py
simulation/conversation_designs.py -> build_simulation_persona()
```

`app/ai/personas.py` defines reusable tenant templates. `build_simulation_persona()` adapts a template to the selected scenario property, including bedrooms, rent, household income, property location, and the simulation mobile number.

Static landlord scenarios live in:

```text
simulation/scenario_library.py
simulation/scenarios/generators.py
```

Current seeded scenarios include:

- `normal_viewing_offer`
- `screening_before_viewing`
- `phone_refusal_before_viewing`
- `asks_for_tenant_phone_early`
- `vague_landlord_reply`
- `viewing_confirmed_then_coordination`
- `outreach-screening-before-phone`
- `outreach-phone-request`
- `reply-after-landlord-question`
- `screening-before-phone`

Current active conversation designs:

- `viewing_first_v1`: baseline; arrange or nearly arrange a viewing before asking for contact details.
- `screening_first_v1`: build landlord confidence by answering screening concerns before progressing to viewing/contact.
- `confirmation_close_v1`: strict gate; ask for the number only after a concrete viewing time is agreed or nearly agreed, using a logistics reason.
- `tenant_shares_first_v1`: reciprocity; share the tenant mobile first after viewing progress, then let the landlord reciprocate if useful.
- `landlord_preference_v1`: low-pressure channel choice; ask whether the landlord prefers OpenRent messages or phone coordination.

Removed designs:

- `phone_first_v1`
- `soft_human_v1`

## Run Main Dashboard

From `openrent-agent/frontend/dashboard/`:

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

Backend simulation/API tests (run from `openrent-agent/`):

```powershell
pytest tests\simulation tests\test_simulation_api.py tests\test_prompt_persona_flow.py
```

Simulation lab build:

```powershell
cd openrent-agent/frontend/simulation-lab
npm run build
```

Main dashboard build:

```powershell
cd openrent-agent/frontend/dashboard
npm run build
```

## Notes

- The simulation lab is intentionally separate from the main operations dashboard.
- Generated simulation run artifacts and frontend dependency folders should not be committed.
- Testers are currently treated as trusted users, so the lab can show shared session history from `simulation/datasets/runs`.
- Advanced mode may expose prompts, completions, event logs, and runtime context. Use Test mode for client-facing testing.
