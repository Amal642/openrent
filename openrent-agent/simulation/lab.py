from dataclasses import asdict
from datetime import datetime, timezone
import uuid
from pathlib import Path

from fastapi import HTTPException

from simulation.actors.landlord_actor import LandlordActor
from simulation.actors.llm_landlord_actor import LlmLandlordActor
from simulation.engine.deterministic import build_rng
from simulation.engine.event_bus import EventBus
from simulation.engine.orchestrator import SimulationOrchestrator
from simulation.engine.runtime_context import RuntimeContext
from simulation.conversation_designs import (
    VIEWING_FIRST_V1,
    build_simulation_persona,
    default_simulation_persona,
    get_conversation_design,
)
from simulation.policies.aggressive_followup import AggressiveFollowupPolicy
from simulation.policies.minimal_policy import MinimalPolicy
from simulation.policies.production_policy import ProductionPolicy
from simulation.scenarios.generators import (
    get_default_scenario,
    get_outreach_phone_request_scenario,
    get_outreach_screening_before_phone_scenario,
    get_reply_after_landlord_question_scenario,
)
from simulation.sessions.store import JSONSessionStore
from simulation.templates.initial_message_provider import build_initial_message_provider


DEFAULT_SCENARIO_ID = "outreach-screening-before-phone"
DEFAULT_ACTOR_ID = "landlord-default"
DEFAULT_POLICY_ID = "production-policy-v1"

SCENARIO_BUILDERS = {
    DEFAULT_SCENARIO_ID: (
        lambda max_turns, start_mode: get_outreach_screening_before_phone_scenario(
            max_turns=max_turns,
            start_mode=start_mode,
        )
    ),
    "outreach-phone-request": (
        lambda max_turns, start_mode: get_outreach_phone_request_scenario(
            max_turns=max_turns,
            start_mode=start_mode,
        )
    ),
    "reply-after-landlord-question": (
        lambda max_turns, start_mode: get_reply_after_landlord_question_scenario(
            max_turns=max_turns,
            start_mode=start_mode,
        )
    ),
    "screening-before-phone": (
        lambda max_turns, start_mode: get_outreach_screening_before_phone_scenario(
            max_turns=max_turns,
            start_mode=start_mode,
        )
    ),
}

ACTOR_BUILDERS = {
    DEFAULT_ACTOR_ID: LandlordActor,
    "llm-landlord-cooperative": lambda: LlmLandlordActor(persona="cooperative"),
    "llm-landlord-suspicious": lambda: LlmLandlordActor(persona="suspicious"),
    "llm-landlord-brusque": lambda: LlmLandlordActor(persona="brusque"),
}

POLICY_BUILDERS = {
    DEFAULT_POLICY_ID: ProductionPolicy,
    "minimal-policy-v1": MinimalPolicy,
    "aggressive-followup-v1": AggressiveFollowupPolicy,
}


def _resolve_scenario(
    scenario_id: str,
    max_turns: int,
    start_mode: str = "agent_starts",
):
    builder = SCENARIO_BUILDERS.get(scenario_id)
    if builder is None:
        raise HTTPException(status_code=400, detail="Unknown scenario_id")
    return builder(max_turns, start_mode)


def _resolve_actor(actor_id: str):
    builder = ACTOR_BUILDERS.get(actor_id)
    if builder is None:
        raise HTTPException(status_code=400, detail="Unknown actor_id")
    return builder()


def _resolve_policy(
    policy_id: str,
    *,
    conversation_design=None,
    persona: dict | None = None,
    property: dict | None = None,
):
    builder = POLICY_BUILDERS.get(policy_id)
    if builder is None:
        raise HTTPException(status_code=400, detail="Unknown policy_id")
    if builder is ProductionPolicy:
        return builder(
            conversation_design_id=(
                conversation_design.design_id if conversation_design else None
            ),
            conversation_design=(
                asdict(conversation_design) if conversation_design else None
            ),
            persona=persona,
            property=property,
        )
    return builder()


def run_simulation_session(
    *,
    seed: int = 42,
    max_turns: int = 1,
    scenario_id: str | None = None,
    actor_id: str | None = None,
    policy_id: str | None = None,
    start_mode: str = "agent_starts",
    initial_message_source: str | None = None,
    account_id: int | None = None,
    initial_message: str | None = None,
    conversation_design_id: str | None = None,
    hippo=None,
) -> dict:
    """Run one sim session through the orchestrator and return the dict.

    `hippo` is an optional pre-built `HippoSession` (see
    `simulation.engine.hippo_hooks`). When provided, the orchestrator
    fires the HIPPO_RECALL + HIPPO_INGEST hooks; when None (the
    default), behaviour is unchanged. The caller owns the client
    lifecycle \u2014 typically the pilot-matrix runner spawns one client and
    passes the same `HippoSession` to every trial so the snap
    accumulates across trials.
    """

    conversation_design = get_conversation_design(
        conversation_design_id or VIEWING_FIRST_V1,
    )
    scenario = _resolve_scenario(
        scenario_id or DEFAULT_SCENARIO_ID,
        max_turns,
        start_mode,
    )
    persona = build_simulation_persona(scenario.persona_type, scenario.property)
    actor = _resolve_actor(actor_id or DEFAULT_ACTOR_ID)
    policy = _resolve_policy(
        policy_id or DEFAULT_POLICY_ID,
        conversation_design=conversation_design,
        persona=persona,
        property=scenario.property,
    )
    initial_message_provider = None
    if scenario.start_mode == "agent_starts":
        initial_message_provider = build_initial_message_provider(
            source=initial_message_source,
            account_id=account_id,
            initial_message=initial_message,
            conversation_design_id=conversation_design.design_id,
            persona=persona,
            property=scenario.property,
        )

    context = RuntimeContext(
        session_id=str(uuid.uuid4()),
        deterministic_seed=seed,
    )
    context.flags["deterministic"] = True
    context.flags["start_mode"] = scenario.start_mode
    context.flags["conversation_design_id"] = conversation_design.design_id
    context.flags["conversation_design_name"] = conversation_design.name
    context.flags["hippo_memory"] = "on" if hippo is not None else "off"
    context.memory["persona"] = persona
    if initial_message_provider is not None:
        context.flags["initial_message_source"] = initial_message_provider.source
    context.metrics["rng_preview"] = build_rng(seed).randint(1, 1000)

    session = SimulationOrchestrator(
        actor=actor,
        policy=policy,
        scenario=scenario,
        runtime_context=context,
        event_bus=EventBus(),
        initial_message_provider=initial_message_provider,
        hippo=hippo,
    ).run()
    return session.to_dict()


def _created_at_for_session(session: dict, artifact_path: Path) -> str:
    events = session.get("events") or []
    if events and events[0].get("timestamp"):
        return events[0]["timestamp"]
    return datetime.fromtimestamp(
        artifact_path.stat().st_mtime,
        tz=timezone.utc,
    ).isoformat()


def list_simulation_sessions(store: JSONSessionStore | None = None) -> list[dict]:
    session_store = store or JSONSessionStore()
    summaries = []
    for path in session_store.list_paths():
        session = session_store.load(path.stem)
        if session is None:
            continue
        created_at = _created_at_for_session(session, path)
        evaluation = session.get("evaluation") or {}
        observability = session.get("observability") or {}
        summaries.append(
            {
                "session_id": session.get("session_id"),
                "mode": session.get("mode", "simulation"),
                "start_mode": session.get("start_mode", "actor_starts"),
                "initial_message_source": session.get("initial_message_source"),
                "conversation_design_id": session.get("conversation_design_id"),
                "conversation_design_name": session.get("conversation_design_name"),
                "scenario_id": session.get("scenario_id"),
                "actor_id": session.get("actor_id"),
                "policy_id": session.get("policy_id"),
                "score": evaluation.get("score"),
                "passed": evaluation.get("passed"),
                "created_at": created_at,
                "timestamp": created_at,
                "run_duration_ms": observability.get("run_duration_ms"),
            }
        )
    return summaries


def get_simulation_session(
    session_id: str,
    store: JSONSessionStore | None = None,
) -> dict:
    session_store = store or JSONSessionStore()
    session = session_store.load(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


def get_simulation_results(
    session_id: str,
    store: JSONSessionStore | None = None,
) -> dict:
    session = get_simulation_session(session_id, store=store)
    evaluation = session.get("evaluation") or {}
    return {
        "session_id": session.get("session_id"),
        "evaluation": evaluation,
        "conversation_state": session.get("conversation_state") or {},
        "observability": session.get("observability") or {},
        "failure_types": evaluation.get("failure_types") or [],
    }
