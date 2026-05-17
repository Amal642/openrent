from datetime import datetime, timedelta
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.db.repository import (
    get_dashboard_accounts,
    get_dashboard_leads,
    get_dashboard_search_profiles,
    create_account,
    create_search_profile,
    update_account,
    update_search_profile,
    deactivate_search_profile,
    update_conversation_status,
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


class AccountPayload(BaseModel):
    email: str
    password: str = ""
    session_file: str = "session.json"
    initial_message: str = ""
    daily_limit: int = 8
    active: bool = True

app = FastAPI(
    title="OpenRent Automation API"
)

# Allow frontend access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],

    allow_credentials=True,

    allow_methods=["*"],

    allow_headers=["*"],
)


@app.get("/")
def health():

    return {
        "status": "running"
    }


@app.get("/api/leads")
def api_leads(
    status: str = None
):

    leads = get_dashboard_leads(
        status=status
    )

    return leads


@app.get("/api/accounts")
def api_accounts():
    return get_dashboard_accounts()


@app.post("/api/accounts/{account_id}/run")
def api_run_account(account_id: int, background_tasks: BackgroundTasks):
    from app.workers.account_worker import run_one_account_by_id

    background_tasks.add_task(run_one_account_by_id, account_id)
    return {"status": "queued", "account_id": account_id}


@app.post("/api/accounts")
def api_create_account(payload: AccountPayload):
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
def api_update_account(account_id: int, payload: AccountPayload):
    return update_account(
        account_id=account_id,
        email=payload.email,
        password=payload.password or None,
        session_file=payload.session_file,
        initial_message=payload.initial_message,
        daily_limit=payload.daily_limit,
        active=payload.active,
    )


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
        pets_allowed=payload.pets_allowed
    )

    return update_search_profile(
        profile_id=profile.id,
        active=payload.active
    )


@app.patch("/api/search-profiles/{profile_id}")
def api_update_search_profile(
    profile_id: int,
    payload: SearchProfilePayload
):

    return update_search_profile(
        profile_id=profile_id,
        account_id=payload.account_id,
        location=payload.location,
        price_min=payload.price_min,
        price_max=payload.price_max,
        bedrooms_min=payload.bedrooms_min,
        bedrooms_max=payload.bedrooms_max,
        area=payload.area,
        pets_allowed=payload.pets_allowed,
        active=payload.active
    )


@app.delete("/api/search-profiles/{profile_id}")
def api_delete_search_profile(profile_id: int):

    return deactivate_search_profile(
        profile_id=profile_id
    )


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
