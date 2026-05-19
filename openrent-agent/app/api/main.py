from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from app.db.init_db import init_db
from app.db.repository import (
    create_account,
    create_search_profile,
    deactivate_search_profile,
    delete_account,
    get_account,
    get_dashboard_accounts,
    get_dashboard_leads,
    get_dashboard_search_profiles,
    update_account,
    update_conversation_status,
    update_search_profile,
)
from app.db.status import CLOSED, SKIPPED


class SearchProfilePayload(BaseModel):
    account_id: int
    location: str
    price_min: int
    price_max: int
    bedrooms_min: int
    bedrooms_max: int
    area: int
    pets_allowed: bool = False
    active: bool = True


class AccountCreatePayload(BaseModel):
    email: str
    password: str = ""
    session_file: str = "session.json"
    initial_message: str = ""
    daily_limit: int = 8
    active: bool = True


class AccountUpdatePayload(BaseModel):
    email: str | None = None
    password: str | None = None
    session_file: str | None = None
    initial_message: str | None = None
    daily_limit: int | None = None
    active: bool | None = None


class SimulationRunPayload(BaseModel):
    seed: int = 42
    max_turns: int = 1
    scenario_id: str | None = None
    actor_id: str | None = None
    policy_id: str | None = None
    start_mode: str = "agent_starts"
    initial_message_source: str | None = None
    account_id: int | None = None
    initial_message: str | None = None


class InteractiveStartPayload(BaseModel):
    scenario_id: str | None = None
    policy_id: str | None = None
    start_mode: str = "agent_starts"
    initial_message_source: str | None = None
    account_id: int | None = None
    initial_message: str | None = None


class InteractiveMessagePayload(BaseModel):
    message: str

@asynccontextmanager
async def lifespan(app_instance):
    init_db()
    yield


app = FastAPI(
    title="OpenRent Automation API",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_DIST = (
    Path(__file__).resolve().parents[2]
    / "frontend"
    / "openrent-command-center"
    / "dist"
)


def _require_account(account_id: int):
    account = get_account(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    return account


def _serve_frontend_asset(full_path: str = "index.html"):
    target = (FRONTEND_DIST / full_path).resolve()
    if FRONTEND_DIST.exists() and target.exists() and target.is_file():
        return FileResponse(target)

    index_file = FRONTEND_DIST / "index.html"
    if index_file.exists():
        return FileResponse(index_file)

    return JSONResponse(
        {
            "status": "frontend_not_built",
            "message": "Build frontend/openrent-command-center to serve the dashboard.",
        },
        status_code=503,
    )


@app.get("/api/health")
def health():
    return {
        "status": "running"
    }


@app.get("/api/leads")
def api_leads(status: str = None):
    return get_dashboard_leads(status=status)


@app.get("/api/accounts")
def api_accounts():
    return get_dashboard_accounts()


@app.post("/api/accounts/{account_id}/run")
def api_run_account(account_id: int, background_tasks: BackgroundTasks):
    _require_account(account_id)
    from app.workers.account_worker import run_one_account_by_id

    background_tasks.add_task(run_one_account_by_id, account_id)
    return {"status": "queued", "account_id": account_id}


@app.post("/api/accounts")
def api_create_account(payload: AccountCreatePayload):
    account = create_account(
        email=payload.email,
        password=payload.password,
        session_file=payload.session_file,
        initial_message=payload.initial_message,
    )
    return update_account(
        account.id,
        daily_limit=payload.daily_limit,
        active=payload.active,
    )


@app.patch("/api/accounts/{account_id}")
def api_update_account(account_id: int, payload: AccountUpdatePayload):
    _require_account(account_id)
    account = update_account(
        account_id=account_id,
        email=payload.email,
        password=payload.password,
        session_file=payload.session_file,
        initial_message=payload.initial_message,
        daily_limit=payload.daily_limit,
        active=payload.active,
    )
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    return account


@app.post("/api/accounts/{account_id}/toggle")
def api_toggle_account(account_id: int):
    account = _require_account(account_id)
    updated = update_account(
        account_id=account_id,
        active=not account["active"],
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Account not found")
    return updated


@app.delete("/api/accounts/{account_id}")
def api_delete_account(account_id: int):
    _require_account(account_id)
    deleted = delete_account(account_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Account not found")
    return {"account_id": account_id, "deleted": True}


@app.get("/api/search-profiles")
def api_search_profiles():
    return get_dashboard_search_profiles()


@app.post("/api/search-profiles")
def api_create_search_profile(payload: SearchProfilePayload):
    profile = create_search_profile(
        account_id=payload.account_id,
        location=payload.location,
        price_min=payload.price_min,
        price_max=payload.price_max,
        bedrooms_min=payload.bedrooms_min,
        bedrooms_max=payload.bedrooms_max,
        area=payload.area,
        pets_allowed=payload.pets_allowed,
    )

    return update_search_profile(
        profile_id=profile.id,
        active=payload.active,
    )


@app.patch("/api/search-profiles/{profile_id}")
def api_update_search_profile(profile_id: int, payload: SearchProfilePayload):
    profile = update_search_profile(
        profile_id=profile_id,
        account_id=payload.account_id,
        location=payload.location,
        price_min=payload.price_min,
        price_max=payload.price_max,
        bedrooms_min=payload.bedrooms_min,
        bedrooms_max=payload.bedrooms_max,
        area=payload.area,
        pets_allowed=payload.pets_allowed,
        active=payload.active,
    )
    if not profile:
        raise HTTPException(status_code=404, detail="Search profile not found")
    return profile


@app.delete("/api/search-profiles/{profile_id}")
def api_delete_search_profile(profile_id: int):
    profile = deactivate_search_profile(profile_id=profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Search profile not found")
    return profile


@app.post("/api/leads/{thread_id}/complete")
def api_complete_lead(thread_id: str):
    update_conversation_status(thread_id, CLOSED)
    return {"thread_id": thread_id, "status": CLOSED}


@app.post("/api/leads/{thread_id}/skip")
def api_skip_lead(thread_id: str):
    update_conversation_status(thread_id, SKIPPED)
    return {"thread_id": thread_id, "status": SKIPPED}


@app.get("/api/metrics")
def api_metrics():
    leads = get_dashboard_leads()
    accounts = get_dashboard_accounts()
    today = datetime.utcnow().date()

    phones_today = [
        lead for lead in leads
        if lead.get("phone")
        and lead.get("last_message_at")
        and lead["last_message_at"].date() == today
    ]

    by_day = {}
    for lead in leads:
        created_at = lead.get("created_at")
        if not created_at:
            continue
        day = created_at.date().isoformat()
        by_day.setdefault(
            day,
            {"date": day, "leads": 0, "replies": 0, "phones": 0, "failures": 0},
        )
        by_day[day]["leads"] += 1
        if lead.get("last_processed_message"):
            by_day[day]["replies"] += 1
        if lead.get("phone"):
            by_day[day]["phones"] += 1
        if lead.get("status") == "AI_FAILED":
            by_day[day]["failures"] += 1

    for offset in range(13, -1, -1):
        day = (datetime.utcnow().date() - timedelta(days=offset)).isoformat()
        by_day.setdefault(
            day,
            {"date": day, "leads": 0, "replies": 0, "phones": 0, "failures": 0},
        )

    return {
        "total_leads": len(leads),
        "total_phones": len([lead for lead in leads if lead.get("phone")]),
        "phones_today": len(phones_today),
        "daily_phone_target": 3,
        "active_accounts": len([account for account in accounts if account.get("active")]),
        "series": [by_day[day] for day in sorted(by_day.keys())[-14:]],
    }


@app.get("/api/logs")
def api_logs(limit: int = 250):
    log_path = Path("logs/openrent.log")
    if not log_path.exists():
        return []

    lines = log_path.read_text(errors="ignore").splitlines()[-limit:]
    results = []
    for idx, line in enumerate(lines):
        parts = [part.strip() for part in line.split("|", 2)]
        if len(parts) == 3:
            created_at, level, message = parts
        else:
            created_at, level, message = datetime.utcnow().isoformat(), "INFO", line

        category = "worker"
        lower = message.lower()
        if "openai" in lower or "ai" in lower:
            category = "ai"
        elif "login" in lower:
            category = "login"
        elif "retry" in lower:
            category = "retry"
        elif "agent" in lower:
            category = "agent_skip"

        level = level.lower()
        if level == "warning":
            level = "warn"
        if level not in {"info", "warn", "error"}:
            level = "info"

        results.append({
            "id": f"log-{idx}",
            "level": level,
            "category": category,
            "message": message,
            "created_at": created_at,
        })

    return results


@app.post("/simulation/run")
def simulation_run(payload: SimulationRunPayload):
    from simulation.lab import run_simulation_session

    return run_simulation_session(
        seed=payload.seed,
        max_turns=payload.max_turns,
        scenario_id=payload.scenario_id,
        actor_id=payload.actor_id,
        policy_id=payload.policy_id,
        start_mode=payload.start_mode,
        initial_message_source=payload.initial_message_source,
        account_id=payload.account_id,
        initial_message=payload.initial_message,
    )


@app.get("/simulation/sessions")
def simulation_sessions():
    from simulation.lab import list_simulation_sessions

    return list_simulation_sessions()


@app.get("/simulation/sessions/{session_id}")
def simulation_session_detail(session_id: str):
    from simulation.lab import get_simulation_session

    return get_simulation_session(session_id)


@app.get("/simulation/results/{session_id}")
def simulation_results(session_id: str):
    from simulation.lab import get_simulation_results

    return get_simulation_results(session_id)


@app.post("/simulation/interactive/start")
def simulation_interactive_start(payload: InteractiveStartPayload):
    from simulation.interactive import start_interactive_session

    return start_interactive_session(
        scenario_id=payload.scenario_id,
        policy_id=payload.policy_id,
        start_mode=payload.start_mode,
        initial_message_source=payload.initial_message_source,
        account_id=payload.account_id,
        initial_message=payload.initial_message,
    )


@app.get("/simulation/interactive/{session_id}")
def simulation_interactive_detail(session_id: str):
    from simulation.interactive import get_interactive_session

    return get_interactive_session(session_id)


@app.post("/simulation/interactive/{session_id}/message")
def simulation_interactive_message(
    session_id: str,
    payload: InteractiveMessagePayload,
):
    from simulation.interactive import submit_interactive_message

    return submit_interactive_message(session_id, payload.message)


@app.get("/")
def dashboard_index():
    return _serve_frontend_asset()


@app.get("/{full_path:path}")
def dashboard_asset(full_path: str):
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not found")
    return _serve_frontend_asset(full_path)
