from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse
from urllib.parse import quote, urlsplit, urlunsplit
import os
import socket

from fastapi import FastAPI, HTTPException
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
    get_conversation_messages,
    get_dashboard_accounts,
    get_dashboard_leads,
    get_dashboard_search_profiles,
    update_proxy_health,
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
    proxy_server: str | None = None
    proxy_username: str | None = None
    proxy_password: str | None = None
    daily_limit: int = 8
    active: bool = True
    mobile_number: str | None = None
    persona_type: str | None = None
    phone_fetching_type: str | None = None
    message_strategy: str | None = None
    escalation_behavior: str | None = None
    conversation_goal: str | None = None
    conversation_style: str | None = None


class AccountUpdatePayload(BaseModel):
    email: str | None = None
    password: str | None = None
    session_file: str | None = None
    initial_message: str | None = None
    proxy_server: str | None = None
    proxy_username: str | None = None
    proxy_password: str | None = None
    daily_limit: int | None = None
    active: bool | None = None
    mobile_number: str | None = None
    persona_type: str | None = None
    phone_fetching_type: str | None = None
    message_strategy: str | None = None
    escalation_behavior: str | None = None
    conversation_goal: str | None = None
    conversation_style: str | None = None


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
    conversation_design_id: str | None = None


class InteractiveStartPayload(BaseModel):
    scenario_id: str | None = None
    policy_id: str | None = None
    start_mode: str = "agent_starts"
    initial_message_source: str | None = None
    account_id: int | None = None
    initial_message: str | None = None
    conversation_design_id: str | None = None


class InteractiveMessagePayload(BaseModel):
    message: str


class CompareDesignsPayload(BaseModel):
    scenario_id: str | None = None
    initial_landlord_message: str | None = None
    conversation_design_ids: list[str]
    max_turns: int = 1


class SettingsPayload(BaseModel):
    openai_model: str | None = None
    auto_send: bool | None = None
    worker_concurrency: int | None = None
    min_delay_seconds: int | None = None
    max_delay_seconds: int | None = None
    retry_limit: int | None = None
    daily_message_limit: int | None = None


RUNTIME_SETTINGS = {
    "openai_model": os.getenv("OPENAI_REPLY_MODEL", "gpt-4.1-mini"),
    "auto_send": os.getenv("AI_AUTOSEND", "true").lower() == "true",
    "worker_concurrency": int(os.getenv("WORKER_CONCURRENCY", "4")),
    "min_delay_seconds": int(os.getenv("MIN_DELAY_SECONDS", "45")),
    "max_delay_seconds": int(os.getenv("MAX_DELAY_SECONDS", "180")),
    "retry_limit": int(os.getenv("RETRY_LIMIT", "3")),
    "daily_message_limit": int(os.getenv("DEFAULT_DAILY_MESSAGE_LIMIT", "8")),
}

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
    / "dashboard"
    / "dist"
)


def _require_account(account_id: int):
    account = get_account(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    return account


def _set_worker_state(account_id: int, status: str, phase: str | None = None):
    from app.db.repository import update_account_worker_state

    update_account_worker_state(account_id, status, phase=phase)
    account = get_account(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    return account


def _proxy_host_port(proxy_server: str):
    parsed = urlparse(proxy_server if "://" in proxy_server else f"http://{proxy_server}")
    if not parsed.hostname or not parsed.port:
        raise ValueError("Proxy must include host and port")
    return parsed.hostname, parsed.port


def _account_proxy_url(account: dict):
    proxy_server = (account.get("proxy_server") or "").strip()
    if not proxy_server:
        return None

    parsed = urlsplit(
        proxy_server if "://" in proxy_server else f"http://{proxy_server}"
    )
    username_value = account.get("proxy_username")
    if not username_value:
        return urlunsplit(parsed)

    username = quote(username_value, safe="")
    password = quote(account.get("proxy_password") or "", safe="")
    netloc = parsed.netloc.split("@", 1)[-1]
    return urlunsplit(
        (
            parsed.scheme,
            f"{username}:{password}@{netloc}",
            parsed.path,
            parsed.query,
            parsed.fragment,
        )
    )


def _check_and_persist_proxy(account_id: int):
    from app.proxy.check_proxy import check_proxy

    account = _require_account(account_id)
    proxy_url = _account_proxy_url(account)
    if not proxy_url:
        result = {
            "account_id": account_id,
            "healthy": False,
            "status": "not_configured",
            "ok": False,
            "error": "No proxy configured",
        }
        update_proxy_health(account_id, result)
        return result

    result = check_proxy(proxy_url)
    update_proxy_health(account_id, result)
    return {
        "account_id": account_id,
        "healthy": result.get("healthy", False),
        "ok": result.get("healthy", False),
        "status": "ok" if result.get("healthy") else "failed",
        "ip": result.get("ip"),
        "latency": result.get("latency"),
        "status_code": result.get("status_code"),
        "error": result.get("error"),
        "detail": result.get("error"),
    }


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
            "message": "Build frontend/dashboard to serve the dashboard.",
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


@app.get("/api/conversations/{thread_id}/messages")
def api_conversation_messages(thread_id: str):
    return get_conversation_messages(thread_id)


@app.get("/api/accounts")
def api_accounts():
    return get_dashboard_accounts()


@app.get("/api/proxy-health")
def api_proxy_health():
    accounts = get_dashboard_accounts()
    return [
        {
            "account_id": account["id"],
            "account_email": account["email"],
            "proxy_server": account.get("proxy_server"),
            "proxy_status": (
                account.get("proxy_status")
                or ("not_configured" if not account.get("proxy_server") else "unknown")
            ),
            "proxy_ip": account.get("proxy_ip"),
            "proxy_latency": account.get("proxy_latency"),
            "proxy_last_checked": account.get("proxy_last_checked"),
            "proxy_last_error": account.get("proxy_last_error"),
            "proxy_failures": account.get("proxy_failures", 0),
        }
        for account in accounts
    ]


@app.post("/api/accounts/{account_id}/run")
async def api_run_account(account_id: int):
    _require_account(account_id)
    from app.workers.account_worker import start_account_worker

    await start_account_worker(account_id)
    return {"status": "queued", "account_id": account_id}


@app.post("/api/accounts")
def api_create_account(payload: AccountCreatePayload):
    account = create_account(
        email=payload.email,
        password=payload.password,
        session_file=payload.session_file,
        initial_message=payload.initial_message,
        proxy_server=payload.proxy_server,
        proxy_username=payload.proxy_username,
        proxy_password=payload.proxy_password,
        mobile_number=payload.mobile_number,
        persona_type=payload.persona_type,
        phone_fetching_type=payload.phone_fetching_type,
        message_strategy=payload.message_strategy,
        escalation_behavior=payload.escalation_behavior,
        conversation_goal=payload.conversation_goal,
        conversation_style=payload.conversation_style,
    )
    return update_account(
        account.id,
        daily_limit=payload.daily_limit,
        active=payload.active,
        mobile_number=payload.mobile_number,
        persona_type=payload.persona_type,
        phone_fetching_type=payload.phone_fetching_type,
        message_strategy=payload.message_strategy,
        escalation_behavior=payload.escalation_behavior,
        conversation_goal=payload.conversation_goal,
        conversation_style=payload.conversation_style,
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
        proxy_server=payload.proxy_server,
        proxy_username=payload.proxy_username,
        proxy_password=payload.proxy_password,
        daily_limit=payload.daily_limit,
        active=payload.active,
        mobile_number=payload.mobile_number,
        persona_type=payload.persona_type,
        phone_fetching_type=payload.phone_fetching_type,
        message_strategy=payload.message_strategy,
        escalation_behavior=payload.escalation_behavior,
        conversation_goal=payload.conversation_goal,
        conversation_style=payload.conversation_style,
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


@app.post("/api/accounts/{account_id}/start")
async def api_start_account(account_id: int):
    _require_account(account_id)
    update_account(account_id=account_id, active=True)
    from app.workers.account_worker import start_account_worker

    await start_account_worker(account_id)
    return get_account(account_id)


@app.post("/api/accounts/{account_id}/stop")
async def api_stop_account(account_id: int):
    _require_account(account_id)
    update_account(account_id=account_id, active=False)
    from app.workers.account_worker import stop_account_worker

    await stop_account_worker(account_id)
    return get_account(account_id)


@app.post("/api/accounts/{account_id}/pause")
def api_pause_account(account_id: int):
    _require_account(account_id)
    update_account(account_id=account_id, active=False)
    return _set_worker_state(account_id, "paused", phase="paused")


@app.post("/api/accounts/{account_id}/resume")
def api_resume_account(account_id: int):
    _require_account(account_id)
    update_account(account_id=account_id, active=True)
    return _set_worker_state(account_id, "idle", phase="idle")


@app.post("/api/accounts/{account_id}/test-proxy")
def api_test_proxy(account_id: int):
    return _check_and_persist_proxy(account_id)


@app.post("/api/accounts/{account_id}/check-proxy")
def api_check_proxy(account_id: int):
    return _check_and_persist_proxy(account_id)


@app.post("/api/accounts/{account_id}/refresh-session")
async def api_refresh_session(account_id: int):
    _require_account(account_id)
    from app.workers.account_worker import start_account_worker

    await start_account_worker(account_id)
    _set_worker_state(account_id, "running", phase="refreshing_session")
    return get_account(account_id)


@app.post("/api/accounts/{account_id}/invalidate-session")
def api_invalidate_session(account_id: int):
    account = _require_account(account_id)
    from app.browser.launcher import get_session_file

    session_file = get_session_file(type("AccountRef", (), account))
    if session_file and Path(session_file).exists():
        Path(session_file).unlink()
    return _set_worker_state(account_id, "idle", phase="session_invalidated")


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
        and lead.get("phone_found_at")
        and lead["phone_found_at"].date() == today
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
            phone_day = (lead.get("phone_found_at") or created_at).date().isoformat()
            by_day.setdefault(
                phone_day,
                {"date": phone_day, "leads": 0, "replies": 0, "phones": 0, "failures": 0},
            )
            by_day[phone_day]["phones"] += 1
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


@app.get("/api/workers")
def api_workers():
    accounts = get_dashboard_accounts()
    now = datetime.utcnow()
    return [
        {
            "id": f"account-{account['id']}",
            "account_id": account["id"],
            "account_email": account["email"],
            "status": account.get("worker_status", "idle"),
            "phase": account.get("current_worker_phase", "idle"),
            "last_heartbeat": account.get("worker_last_heartbeat"),
            "started_at": account.get("worker_started_at"),
            "last_completed_at": account.get("worker_last_completed_at"),
            "job_id": account.get("worker_job_id"),
            "retry_count": account.get("retry_count", 0),
            "retry_next_at": account.get("retry_next_at"),
            "last_error": account.get("worker_last_error"),
            "active": account.get("active", False),
            "stale": bool(
                account.get("worker_status") == "running"
                and account.get("worker_last_heartbeat")
                and (now - account["worker_last_heartbeat"]).total_seconds() > 120
            ),
        }
        for account in accounts
    ]


@app.get("/api/workers/status")
def api_workers_status():
    from app.workers.account_worker import get_active_worker_count

    workers = api_workers()
    return {
        "total": len(workers),
        "running": len([worker for worker in workers if worker["status"] in {"running", "stopping"}]),
        "paused": len([worker for worker in workers if worker["status"] == "paused"]),
        "errored": len([
            worker for worker in workers
            if worker["status"] in {"error", "proxy_error", "login_error"}
        ]),
        "queue": "in_process",
        "active_tasks": get_active_worker_count(),
    }


@app.get("/api/settings")
def api_settings():
    return {
        **RUNTIME_SETTINGS,
        "backend_status": "running",
        "redis_status": "not_configured",
        "api_status": "ok",
    }


@app.patch("/api/settings")
def api_update_settings(payload: SettingsPayload):
    updates = payload.dict(exclude_unset=True)
    RUNTIME_SETTINGS.update({key: value for key, value in updates.items() if value is not None})
    return api_settings()


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
        conversation_design_id=payload.conversation_design_id,
    )


@app.get("/simulation/conversation-designs")
def simulation_conversation_designs():
    from simulation.conversation_designs import list_conversation_designs

    return list_conversation_designs()


@app.get("/simulation/scenarios")
def simulation_scenarios():
    from simulation.scenario_library import list_conversation_scenarios

    return list_conversation_scenarios()


@app.get("/simulation/interactive-scenarios")
def simulation_interactive_scenarios():
    from simulation.scenarios.generators import list_interactive_scenarios

    return list_interactive_scenarios()


@app.post("/simulation/compare-designs")
def simulation_compare_designs(payload: CompareDesignsPayload):
    from simulation.compare import compare_conversation_designs

    return compare_conversation_designs(
        scenario_id=payload.scenario_id,
        initial_landlord_message=payload.initial_landlord_message,
        conversation_design_ids=payload.conversation_design_ids,
        max_turns=payload.max_turns,
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
        conversation_design_id=payload.conversation_design_id,
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
