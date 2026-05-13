from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.db.repository import (
    get_dashboard_leads,
    get_active_accounts,
    get_dashboard_search_profiles,
    create_search_profile,
    update_search_profile,
    deactivate_search_profile
)


class SearchProfilePayload(BaseModel):
    account_id: int
    location: str
    price_min: int
    price_max: int
    bedrooms_min: int
    bedrooms_max: int
    pets_allowed: bool = False
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
        pets_allowed=payload.pets_allowed,
        active=payload.active
    )


@app.delete("/api/search-profiles/{profile_id}")
def api_delete_search_profile(profile_id: int):

    return deactivate_search_profile(
        profile_id=profile_id
    )
