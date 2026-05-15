from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from simulation.lab import (
    get_simulation_results,
    get_simulation_session,
    list_simulation_sessions,
    run_simulation_session,
)
from simulation.interactive import (
    get_interactive_session,
    start_interactive_session,
    submit_interactive_message,
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

app = FastAPI(
    title="OpenRent Automation API"
)


def _repository():
    from app.db import repository

    return repository

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

    repository = _repository()
    leads = repository.get_dashboard_leads(
        status=status
    )
    return leads


@app.get("/api/accounts")
def api_accounts():

    accounts = _repository().get_active_accounts()

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

    return _repository().get_dashboard_search_profiles()


@app.post("/api/search-profiles")
def api_create_search_profile(payload: SearchProfilePayload):

    repository = _repository()
    profile = repository.create_search_profile(
        account_id=payload.account_id,
        location=payload.location,
        price_min=payload.price_min,
        price_max=payload.price_max,
        bedrooms_min=payload.bedrooms_min,
        bedrooms_max=payload.bedrooms_max,
        area=payload.area,
        pets_allowed=payload.pets_allowed
    )

    return repository.update_search_profile(
        profile_id=profile.id,
        active=payload.active
    )


@app.patch("/api/search-profiles/{profile_id}")
def api_update_search_profile(
    profile_id: int,
    payload: SearchProfilePayload
):

    return _repository().update_search_profile(
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

    return _repository().deactivate_search_profile(
        profile_id=profile_id
    )


@app.post("/simulation/run")
def api_run_simulation(payload: SimulationRunPayload):

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
def api_list_simulation_sessions():

    return list_simulation_sessions()


@app.get("/simulation/sessions/{session_id}")
def api_get_simulation_session(session_id: str):

    return get_simulation_session(session_id)


@app.get("/simulation/results/{session_id}")
def api_get_simulation_results(session_id: str):

    return get_simulation_results(session_id)


@app.post("/simulation/interactive/start")
def api_start_interactive_session(payload: InteractiveStartPayload):

    artifact = start_interactive_session(
        scenario_id=payload.scenario_id,
        policy_id=payload.policy_id,
        start_mode=payload.start_mode,
        initial_message_source=payload.initial_message_source,
        account_id=payload.account_id,
        initial_message=payload.initial_message,
    )
    return {"session_id": artifact["session_id"]}


@app.post("/simulation/interactive/{session_id}/message")
def api_submit_interactive_message(
    session_id: str,
    payload: InteractiveMessagePayload,
):

    return submit_interactive_message(session_id, payload.message)


@app.get("/simulation/interactive/{session_id}")
def api_get_interactive_session(session_id: str):

    return get_interactive_session(session_id)
