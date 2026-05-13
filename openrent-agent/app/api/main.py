from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db.repository import (
    get_dashboard_leads,
    get_active_accounts
)

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

    accounts = get_active_accounts()

    results = []

    for account in accounts:

        results.append({

            "id": account.id,

            "email": account.email,

            "daily_limit": account.daily_limit,

            "messages_sent_today": (
                account.messages_sent_today
            ),

            "active": account.active,

            "created_at": account.created_at
        })

    return results