from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse
from urllib.parse import quote, urlsplit, urlunsplit
import os
import socket

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.auth import (
    AUTH_ERROR,
    INVALID_CREDENTIALS_ERROR,
    authenticate,
    clear_failed_logins,
    ensure_login_allowed,
    issue_token,
    record_failed_login,
    validate_auth_config,
    verify_request,
)
from app.db.init_db import init_db
from app.db.repository import (
    clear_account_failed,
    create_account,
    create_location,
    create_proxy,
    create_search_profile,
    deactivate_search_profile,
    delete_account,
    delete_location,
    delete_proxy,
    get_account,
    get_capacity_stats,
    get_conversation_messages,
    get_dashboard_accounts,
    get_dashboard_leads,
    get_dashboard_search_profiles,
    get_failed_account_count,
    get_failed_accounts,
    get_locations,
    get_proxies,
    get_proxy,
    mark_account_failed,
    update_location,
    update_proxy,
    update_proxy_health,
    update_account,
    update_conversation_status,
    update_search_profile,
)
from app.db.status import CLOSED, SKIPPED
from app.services.account_scheduler import (
    start_account_scheduler,
    stop_account_scheduler,
)
from app.services.failed_account_detector import (
    start_failed_account_detector,
    stop_failed_account_detector,
)
from app.services.proxy_health_monitor import (
    start_proxy_health_monitor,
    stop_proxy_health_monitor,
)
from app.services.google_sheets_export_dispatcher import (
    start_google_sheets_export_dispatcher,
    stop_google_sheets_export_dispatcher,
)


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


class LoginPayload(BaseModel):
    username: str
    password: str


class ProxyPayload(BaseModel):
    name: str | None = None
    host: str
    port: int
    username: str | None = None
    password: str | None = None
    is_active: bool = True
    proxy_type: str = "static"


class ProxyUpdatePayload(BaseModel):
    name: str | None = None
    host: str | None = None
    port: int | None = None
    username: str | None = None
    password: str | None = None
    is_active: bool | None = None
    proxy_type: str | None = None


class AccountCreatePayload(BaseModel):
    email: str
    password: str = ""
    session_file: str = ""
    initial_message: str = ""
    proxy_id: int | None = None
    # Legacy direct fields — kept for backward compat; proxy_id takes priority
    proxy_server: str | None = None
    proxy_username: str | None = None
    proxy_password: str | None = None
    daily_limit: int = 5
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
    proxy_id: int | None = None
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


class LocationPayload(BaseModel):
    name: str
    term_value: str
    active: bool = True


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
    "daily_message_limit": int(os.getenv("DEFAULT_DAILY_MESSAGE_LIMIT", "5")),
}

@asynccontextmanager
async def lifespan(app_instance):
    validate_auth_config()
    init_db()
    app_instance.state.account_scheduler_task = start_account_scheduler()
    app_instance.state.proxy_health_monitor_task = start_proxy_health_monitor()
    app_instance.state.failed_account_detector_task = start_failed_account_detector()
    app_instance.state.google_sheets_export_dispatcher_task = (
        start_google_sheets_export_dispatcher()
    )
    try:
        yield
    finally:
        await stop_account_scheduler(
            getattr(app_instance.state, "account_scheduler_task", None)
        )
        await stop_proxy_health_monitor(
            getattr(app_instance.state, "proxy_health_monitor_task", None)
        )
        await stop_failed_account_detector(
            getattr(app_instance.state, "failed_account_detector_task", None)
        )
        await stop_google_sheets_export_dispatcher(
            getattr(
                app_instance.state,
                "google_sheets_export_dispatcher_task",
                None,
            )
        )


app = FastAPI(
    title="OpenRent Automation API",
    lifespan=lifespan,
)


class CRMAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        is_public = path in {"/api/health", "/api/auth/login"}
        if request.method != "OPTIONS" and path.startswith("/api/") and not is_public:
            try:
                request.state.crm_username = verify_request(request)
            except HTTPException as exc:
                return JSONResponse(
                    {"detail": AUTH_ERROR},
                    status_code=exc.status_code,
                    headers=exc.headers,
                )
        return await call_next(request)


app.add_middleware(CRMAuthMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://openrent-tjv2.vercel.app",
        "https://openrent-api.bricbybric.ae",
        "http://localhost:5173",
        "http://localhost:4173",],
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

_SCREENSHOTS_ROOT = Path("screenshots") / "threads"
_SCREENSHOTS_ROOT.mkdir(parents=True, exist_ok=True)


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


def _proxy_url_for_account_id(account_id: int) -> str | None:
    """
    Build a proxy URL for an account, handling both the legacy proxy_server
    field and the linked Proxy record (proxy_id).
    """
    from app.db.models import Account as _Account, Proxy as _Proxy
    from app.db.connection import SessionLocal

    db = SessionLocal()
    try:
        account = db.query(_Account).filter(_Account.id == account_id).first()
        if not account:
            return None

        # Prefer linked Proxy record
        if account.proxy_id:
            proxy = db.query(_Proxy).filter(_Proxy.id == account.proxy_id).first()
            if proxy and proxy.is_active and proxy.host:
                server = f"http://{proxy.host}:{proxy.port}"
                if not proxy.username:
                    return server
                username = quote(proxy.username, safe="")
                password = quote(proxy.password or "", safe="")
                return f"http://{username}:{password}@{proxy.host}:{proxy.port}"

        # Fall back to legacy direct fields
        proxy_server = (account.proxy_server or "").strip()
        if not proxy_server:
            return None
        parsed = urlsplit(proxy_server if "://" in proxy_server else f"http://{proxy_server}")
        if not account.proxy_username:
            return urlunsplit(parsed)
        username = quote(account.proxy_username, safe="")
        password = quote(account.proxy_password or "", safe="")
        netloc = parsed.netloc.split("@", 1)[-1]
        return urlunsplit((parsed.scheme, f"{username}:{password}@{netloc}", parsed.path, parsed.query, parsed.fragment))
    finally:
        db.close()


def _check_and_persist_proxy(account_id: int):
    from app.proxy.check_proxy import check_proxy

    proxy_url = _proxy_url_for_account_id(account_id)
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


@app.post("/api/auth/login")
def api_login(payload: LoginPayload, request: Request):
    ip_address = request.client.host if request.client else "unknown"
    ensure_login_allowed(ip_address)
    if not authenticate(payload.username, payload.password):
        record_failed_login(ip_address)
        raise HTTPException(status_code=401, detail=INVALID_CREDENTIALS_ERROR)

    clear_failed_logins(ip_address)
    return {
        "token": issue_token(payload.username),
        "username": payload.username,
        "expires_in": 7 * 24 * 60 * 60,
    }


@app.get("/api/auth/me")
def api_auth_me(request: Request):
    return {"username": request.state.crm_username}


@app.get("/api/leads")
def api_leads(status: str = None):
    return get_dashboard_leads(status=status)


@app.get("/api/google-sheet/exports")
def api_google_sheet_exports(status: str = None, limit: int = 100):
    from app.db.repository import get_sheet_export_statuses

    return get_sheet_export_statuses(status=status, limit=limit)


@app.post("/api/google-sheet/exports/{export_id}/retry")
def api_retry_google_sheet_export(export_id: int):
    from app.db.repository import reset_sheet_export_to_pending

    if not reset_sheet_export_to_pending(export_id):
        raise HTTPException(status_code=404, detail="Sheet export not found")
    return {"export_id": export_id, "status": "PENDING"}


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
                or ("not_configured" if not account.get("proxy_server") and not account.get("proxy_id") else "unknown")
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

    result = await start_account_worker(account_id)
    return {
        "status": "queued" if result.get("queued") else "skipped",
        "account_id": account_id,
        **result,
    }


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
        proxy_id=payload.proxy_id,
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
        proxy_id=payload.proxy_id,
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

    result = await start_account_worker(account_id)
    if result.get("queued"):
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


@app.get("/api/proxies")
def api_list_proxies():
    return get_proxies()


@app.post("/api/proxies")
def api_create_proxy(payload: ProxyPayload):
    return create_proxy(
        name=payload.name or None,
        host=payload.host,
        port=payload.port,
        username=payload.username or None,
        password=payload.password or None,
        is_active=payload.is_active,
        proxy_type=payload.proxy_type,
    )


@app.patch("/api/proxies/{proxy_id}")
def api_update_proxy(proxy_id: int, payload: ProxyUpdatePayload):
    updated = update_proxy(
        proxy_id,
        name=payload.name,
        host=payload.host,
        port=payload.port,
        username=payload.username,
        password=payload.password,
        is_active=payload.is_active,
        proxy_type=payload.proxy_type,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Proxy not found")
    return updated


@app.delete("/api/proxies/{proxy_id}")
def api_delete_proxy(proxy_id: int):
    result, error = delete_proxy(proxy_id)
    if error == "not_found":
        raise HTTPException(status_code=404, detail="Proxy not found")
    if error and error.startswith("in_use:"):
        count = error.split(":")[1]
        raise HTTPException(
            status_code=409,
            detail=f"Proxy is assigned to {count} account(s). Reassign accounts before deleting.",
        )
    return result


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
        "daily_phone_target": len([a for a in accounts if a.get("active")]) * 3,
        "active_accounts": len([account for account in accounts if account.get("active")]),
        "series": [by_day[day] for day in sorted(by_day.keys())[-14:]],
    }


@app.get("/api/workers")
def api_workers():
    accounts = get_dashboard_accounts()
    now = datetime.now(timezone.utc)
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
    workers = api_workers()
    active_tasks = 0
    queue_status = "in_process"
    try:
        from app.workers.account_worker import get_active_worker_count

        active_tasks = get_active_worker_count()
    except ModuleNotFoundError:
        queue_status = "worker_dependencies_missing"
    except Exception:
        queue_status = "worker_queue_unavailable"

    return {
        "total": len(workers),
        "running": len([worker for worker in workers if worker["status"] in {"running", "stopping"}]),
        "paused": len([worker for worker in workers if worker["status"] == "paused"]),
        "errored": len([
            worker for worker in workers
            if worker["status"] in {"error", "proxy_error", "login_error"}
        ]),
        "queue": queue_status,
        "active_tasks": active_tasks,
    }


@app.get("/api/capacity")
def api_capacity():
    from app.services.account_scheduler import MAX_PARALLEL_WORKERS

    stats = get_capacity_stats()
    stats["max_parallel_workers"] = MAX_PARALLEL_WORKERS
    stats["worker_capacity"] = max(0, MAX_PARALLEL_WORKERS - stats["accounts_in_flight"])
    return stats


@app.get("/api/settings")
def api_settings():
    try:
        from app.queue.redis_conn import redis_conn
        redis_conn.ping()
        redis_status = "running"
    except Exception:
        redis_status = "error"
    return {
        **RUNTIME_SETTINGS,
        "backend_status": "running",
        "redis_status": redis_status,
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
            raw_ts, level, message = parts
            # Logger uses Python's %(asctime)s format: "2026-06-07 14:23:45,123"
            # Convert to ISO 8601 so JavaScript Date() can parse it.
            try:
                ts = datetime.strptime(raw_ts, "%Y-%m-%d %H:%M:%S,%f")
                created_at = ts.isoformat()
            except ValueError:
                try:
                    ts = datetime.strptime(raw_ts, "%Y-%m-%d %H:%M:%S")
                    created_at = ts.isoformat()
                except ValueError:
                    created_at = datetime.utcnow().isoformat()
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


# =========================================================
# LOCATIONS
# =========================================================

@app.get("/api/locations")
def api_list_locations(active_only: bool = False):
    return get_locations(active_only=active_only)


@app.post("/api/locations")
def api_create_location(payload: LocationPayload):
    return create_location(
        name=payload.name,
        term_value=payload.term_value,
        active=payload.active,
    )


@app.patch("/api/locations/{location_id}")
def api_update_location(location_id: int, payload: LocationPayload):
    updated = update_location(
        location_id,
        name=payload.name,
        term_value=payload.term_value,
        active=payload.active,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Location not found")
    return updated


@app.post("/api/locations/{location_id}/toggle")
def api_toggle_location(location_id: int):
    from app.db.repository import get_locations as _get_locs
    locs = _get_locs()
    loc = next((l for l in locs if l["id"] == location_id), None)
    if not loc:
        raise HTTPException(status_code=404, detail="Location not found")
    updated = update_location(location_id, active=not loc["active"])
    if not updated:
        raise HTTPException(status_code=404, detail="Location not found")
    return updated


@app.delete("/api/locations/{location_id}")
def api_delete_location(location_id: int):
    result, error = delete_location(location_id)
    if error == "not_found":
        raise HTTPException(status_code=404, detail="Location not found")
    return result


# =========================================================
# FAILED ACCOUNTS
# =========================================================

@app.get("/api/failed-accounts")
def api_failed_accounts():
    return get_failed_accounts()


@app.get("/api/failed-accounts/count")
def api_failed_accounts_count():
    return {"count": get_failed_account_count()}


@app.post("/api/failed-accounts/{account_id}/retry")
async def api_retry_failed_account(account_id: int):
    _require_account(account_id)
    clear_account_failed(account_id)
    from app.workers.account_worker import start_account_worker
    result = await start_account_worker(account_id)
    return {
        "status": "queued" if result.get("queued") else "skipped",
        "account_id": account_id,
        **result,
    }


@app.post("/api/failed-accounts/{account_id}/clear")
def api_clear_failed_account(account_id: int):
    account = clear_account_failed(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    return account


@app.post("/api/failed-accounts/{account_id}/disable")
def api_disable_failed_account(account_id: int):
    _require_account(account_id)
    account = update_account(account_id=account_id, active=False)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    return account


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


@app.get("/screenshots/{thread_id}/{filename}")
def thread_screenshot(thread_id: str, filename: str):
    """Serve a numbered screenshot for a thread — no auth required.
    e.g. /screenshots/44338031/1.png"""
    if not filename.endswith(".png"):
        raise HTTPException(status_code=400, detail="Only .png files are served")
    path = Path("screenshots") / "threads" / thread_id / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Screenshot {filename} not found for thread {thread_id}")
    return FileResponse(str(path), media_type="image/png")


@app.get("/screenshots/{thread_id}")
def thread_screenshot_latest(thread_id: str):
    """Serve the most recently saved screenshot for a thread."""
    folder = Path("screenshots") / "threads" / thread_id
    if not folder.exists():
        raise HTTPException(status_code=404, detail="No screenshots found for this thread")
    pngs = sorted(
        [f for f in folder.iterdir() if f.suffix == ".png" and f.stem.isdigit()],
        key=lambda f: int(f.stem),
    )
    if not pngs:
        raise HTTPException(status_code=404, detail="No screenshots found for this thread")
    return FileResponse(str(pngs[-1]), media_type="image/png")


@app.get("/")
def dashboard_index():
    return _serve_frontend_asset()


@app.get("/{full_path:path}")
def dashboard_asset(full_path: str):
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not found")
    return _serve_frontend_asset(full_path)
