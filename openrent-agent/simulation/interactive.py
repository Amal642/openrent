import time
import uuid

from fastapi import HTTPException

from simulation.actors.human_actor import HumanActor
from simulation.engine.event_bus import EventBus
from simulation.engine.runtime_context import RuntimeContext
from simulation.engine.session_manager import (
    emit_event,
    finalize_session,
    generate_agent_reply,
    metrics_from_session,
    update_context_from_agent_message,
    update_context_from_actor_message,
)
from simulation.conversation_designs import (
    VIEWING_FIRST_V1,
    default_simulation_persona,
    get_conversation_design,
)
from simulation.lab import DEFAULT_POLICY_ID, DEFAULT_SCENARIO_ID, _resolve_policy, _resolve_scenario
from simulation.sessions.event_models import SimulationEvent
from simulation.sessions.store import JSONSessionStore
from simulation.templates.initial_message_provider import build_initial_message_provider


INTERACTIVE_MAX_TURNS = 25


def _restore_event_bus(events_payload: list[dict] | None) -> EventBus:
    event_bus = EventBus()
    for event in events_payload or []:
        if event["event_type"] in {"EVALUATION_COMPLETED", "SESSION_FINISHED"}:
            continue
        event_bus.emit(
            SimulationEvent(
                event_type=event["event_type"],
                turn_index=event["turn_index"],
                timestamp=event["timestamp"],
                payload=event["payload"],
            )
        )
    return event_bus


def _session_store(store: JSONSessionStore | None = None) -> JSONSessionStore:
    return store or JSONSessionStore()


def start_interactive_session(
    *,
    scenario_id: str | None = None,
    policy_id: str | None = None,
    start_mode: str = "agent_starts",
    initial_message_source: str | None = None,
    account_id: int | None = None,
    initial_message: str | None = None,
    conversation_design_id: str | None = None,
    store: JSONSessionStore | None = None,
) -> dict:
    conversation_design = get_conversation_design(
        conversation_design_id or VIEWING_FIRST_V1,
    )
    persona = default_simulation_persona()
    scenario = _resolve_scenario(
        scenario_id or DEFAULT_SCENARIO_ID,
        INTERACTIVE_MAX_TURNS,
        start_mode,
    )
    policy = _resolve_policy(
        policy_id or DEFAULT_POLICY_ID,
        conversation_design=conversation_design,
        persona=persona,
    )
    actor = HumanActor()
    initial_message_provider = None
    if scenario.start_mode == "agent_starts":
        initial_message_provider = build_initial_message_provider(
            source=initial_message_source,
            account_id=account_id,
            initial_message=initial_message,
            conversation_design_id=conversation_design.design_id,
        )
    context = RuntimeContext(
        session_id=str(uuid.uuid4()),
        deterministic_seed=0,
    )
    context.flags["deterministic"] = False
    context.flags["interactive"] = True
    context.flags["start_mode"] = scenario.start_mode
    context.flags["conversation_design_id"] = conversation_design.design_id
    context.flags["conversation_design_name"] = conversation_design.name
    context.memory["persona"] = persona
    if initial_message_provider is not None:
        context.flags["initial_message_source"] = initial_message_provider.source
    context.metrics["interactive_turns"] = 0
    event_bus = EventBus()
    metrics = metrics_from_session(None)
    session_started = time.perf_counter()

    emit_event(
        event_bus,
        context,
        "SCENARIO_STARTED",
        {
            "scenario_id": scenario.scenario_id,
            "policy_id": policy.policy_id,
            "actor_id": actor.profile.actor_id,
            "mode": "interactive",
            "start_mode": scenario.start_mode,
            "conversation_design_id": conversation_design.design_id,
        },
    )
    if initial_message_provider is not None:
        initial_message_text = initial_message_provider.get_message()
        emit_event(
            event_bus,
            context,
            "AGENT_INITIAL_MESSAGE_SENT",
            {
                "message": initial_message_text,
                "source": initial_message_provider.source,
            },
        )
        emit_event(
            event_bus,
            context,
            "MEMORY_UPDATED",
            update_context_from_agent_message(
                context,
                initial_message_text,
                key="initial_agent_message",
            ),
        )
    return finalize_session(
        mode="interactive",
        actor=actor,
        policy=policy,
        scenario=scenario,
        context=context,
        event_bus=event_bus,
        metrics=metrics,
        session_started=session_started,
        store=_session_store(store),
    ).to_dict()


def submit_interactive_message(
    session_id: str,
    actor_message: str,
    *,
    store: JSONSessionStore | None = None,
) -> dict:
    if not actor_message.strip():
        raise HTTPException(status_code=400, detail="Message is required")

    session_store = _session_store(store)
    session = session_store.load(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.get("mode") != "interactive":
        raise HTTPException(
            status_code=400,
            detail="Only interactive sessions accept manual messages",
        )
    if session.get("runtime_context", {}).get("current_turn", 0) >= session.get(
        "max_turns",
        INTERACTIVE_MAX_TURNS,
    ):
        raise HTTPException(
            status_code=400,
            detail="Interactive session reached the turn limit",
        )

    scenario = _resolve_scenario(
        session["scenario_id"],
        session["max_turns"],
        session.get("start_mode", "actor_starts"),
    )
    conversation_design = get_conversation_design(
        session.get("conversation_design_id")
        or session.get("runtime_context", {})
        .get("flags", {})
        .get("conversation_design_id")
    )
    persona = (
        session.get("runtime_context", {})
        .get("memory", {})
        .get("persona")
        or default_simulation_persona()
    )
    policy = _resolve_policy(
        session["policy_id"],
        conversation_design=conversation_design,
        persona=persona,
    )
    actor = HumanActor()
    context = RuntimeContext.from_snapshot(session.get("runtime_context"))
    event_bus = _restore_event_bus(session.get("events"))
    metrics = metrics_from_session(session)
    session_started = time.perf_counter() - (
        (session.get("observability") or {}).get("run_duration_ms", 0) / 1000
    )

    context.current_turn += 1
    context.metrics["interactive_turns"] = context.current_turn

    emit_event(
        event_bus,
        context,
        "ACTOR_RESPONDED",
        {
            "speaker": actor.profile.display_name,
            "message": actor_message,
        },
    )
    memory_payload = update_context_from_actor_message(context, actor_message)
    emit_event(event_bus, context, "MEMORY_UPDATED", memory_payload)
    if memory_payload.get("phone_detected"):
        emit_event(
            event_bus,
            context,
            "PHONE_DETECTED",
            {"phone": memory_payload["phone_detected"]},
        )

    generate_agent_reply(policy, context, event_bus, metrics)

    return finalize_session(
        mode="interactive",
        actor=actor,
        policy=policy,
        scenario=scenario,
        context=context,
        event_bus=event_bus,
        metrics=metrics,
        session_started=session_started,
        store=session_store,
    ).to_dict()


def get_interactive_session(
    session_id: str,
    *,
    store: JSONSessionStore | None = None,
) -> dict:
    session = _session_store(store).load(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.get("mode") != "interactive":
        raise HTTPException(status_code=400, detail="Session is not interactive")
    return session
