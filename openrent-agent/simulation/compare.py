import time
import uuid

from fastapi import HTTPException

from simulation.actors.human_actor import HumanActor
from simulation.conversation_designs import (
    PHONE_FIRST_V1,
    VIEWING_FIRST_V1,
    default_simulation_persona,
    get_conversation_design,
)
from simulation.engine.event_bus import EventBus
from simulation.engine.runtime_context import RuntimeContext
from simulation.engine.session_manager import (
    emit_event,
    finalize_session,
    generate_agent_reply,
    metrics_from_session,
    update_context_from_actor_message,
    update_context_from_agent_message,
)
from simulation.lab import DEFAULT_POLICY_ID, DEFAULT_SCENARIO_ID, _resolve_policy, _resolve_scenario
from simulation.scenario_library import get_conversation_scenario
from simulation.templates.initial_message_provider import build_initial_message_provider


DEFAULT_COMPARE_LANDLORD_MESSAGE = (
    "Can you tell me a bit more about yourselves, and when would you like to view?"
)


class NoopSessionStore:
    def save(self, session):
        return None


def _viewing_progressed(session: dict) -> bool:
    signals = ((session.get("conversation_state") or {}).get("signals") or {})
    if signals:
        return bool(
            signals.get("viewing_requested")
            or signals.get("viewing_time_offered")
            or signals.get("viewing_confirmed")
        )
    dimensions = (session.get("evaluation") or {}).get("dimension_scores") or {}
    if dimensions.get("viewing_progress") == 1.0:
        return True
    transcript_text = " ".join(
        (turn.get("message") or "").lower()
        for turn in session.get("transcript") or []
    )
    return any(
        token in transcript_text
        for token in ["viewing", "view", "come and see", "arrange a time"]
    )


def _viewing_confirmed(session: dict) -> bool:
    signals = ((session.get("conversation_state") or {}).get("signals") or {})
    if signals:
        return bool(signals.get("viewing_confirmed"))
    transcript_text = " ".join(
        (turn.get("message") or "").lower()
        for turn in session.get("transcript") or []
    )
    return any(
        token in transcript_text
        for token in ["confirmed", "tomorrow", "works for me", "see you"]
    )


def _success_signals(session: dict) -> list[str]:
    dimensions = (session.get("evaluation") or {}).get("dimension_scores") or {}
    successes = [
        key
        for key, value in dimensions.items()
        if isinstance(value, (int, float)) and value >= 1.0
    ]
    state_signals = ((session.get("conversation_state") or {}).get("signals") or {})
    successes.extend(
        key
        for key, value in state_signals.items()
        if value and key not in successes
    )
    return successes


def _summarize_result(session: dict, landlord_message: str) -> dict:
    evaluation = session.get("evaluation") or {}
    runtime_context = session.get("runtime_context") or {}
    extracted_entities = runtime_context.get("extracted_entities") or {}
    conversation_state = session.get("conversation_state") or {}
    state_signals = conversation_state.get("signals") or {}
    return {
        "design_id": session.get("conversation_design_id"),
        "design_name": session.get("conversation_design_name"),
        "scenario_id": session.get("scenario_id"),
        "scenario_name": session.get("scenario_name"),
        "initial_landlord_message": landlord_message,
        "transcript": session.get("transcript") or [],
        "score": evaluation.get("score"),
        "passed": evaluation.get("passed"),
        "failure_reasons": evaluation.get("failure_types") or [],
        "success_signals": _success_signals(session),
        "conversation_state": conversation_state,
        "phone_captured": bool(state_signals.get("phone_captured")) or "phone" in extracted_entities,
        "viewing_progressed": _viewing_progressed(session),
        "viewing_confirmed": _viewing_confirmed(session),
    }


def _run_single_design(
    *,
    design_id: str,
    landlord_message: str,
    scenario_id: str | None,
    scenario_name: str | None,
    max_turns: int,
    deterministic_seed: int,
) -> dict:
    design = get_conversation_design(design_id)
    persona = default_simulation_persona()
    scenario = _resolve_scenario(
        DEFAULT_SCENARIO_ID,
        max_turns,
        "agent_starts",
    )
    policy = _resolve_policy(
        DEFAULT_POLICY_ID,
        conversation_design=design,
        persona=persona,
    )
    actor = HumanActor()
    context = RuntimeContext(
        session_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"{design.design_id}:{landlord_message}")),
        deterministic_seed=deterministic_seed,
    )
    context.flags["deterministic"] = True
    context.flags["compare"] = True
    context.flags["start_mode"] = scenario.start_mode
    context.flags["conversation_design_id"] = design.design_id
    context.flags["conversation_design_name"] = design.name
    context.flags["conversation_scenario_id"] = scenario_id
    context.flags["conversation_scenario_name"] = scenario_name
    context.memory["persona"] = persona

    event_bus = EventBus()
    metrics = metrics_from_session(None)
    session_started = time.perf_counter()
    initial_message_provider = build_initial_message_provider(
        source="fixture",
        conversation_design_id=design.design_id,
    )

    emit_event(
        event_bus,
        context,
        "SCENARIO_STARTED",
        {
            "scenario_id": scenario.scenario_id,
            "policy_id": policy.policy_id,
            "actor_id": actor.profile.actor_id,
            "mode": "compare",
            "start_mode": scenario.start_mode,
            "conversation_design_id": design.design_id,
        },
    )
    initial_message_text = initial_message_provider.get_message()
    emit_event(
        event_bus,
        context,
        "AGENT_INITIAL_MESSAGE_SENT",
        {"message": initial_message_text, "source": initial_message_provider.source},
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

    context.current_turn = 1
    emit_event(
        event_bus,
        context,
        "ACTOR_RESPONDED",
        {"speaker": actor.profile.display_name, "message": landlord_message},
    )
    emit_event(
        event_bus,
        context,
        "MEMORY_UPDATED",
        update_context_from_actor_message(context, landlord_message),
    )
    generate_agent_reply(policy, context, event_bus, metrics)

    session = finalize_session(
        mode="compare",
        actor=actor,
        policy=policy,
        scenario=scenario,
        context=context,
        event_bus=event_bus,
        metrics=metrics,
        session_started=session_started,
        store=NoopSessionStore(),
    ).to_dict()
    session["scenario_id"] = scenario_id
    session["scenario_name"] = scenario_name
    return _summarize_result(session, landlord_message)


def compare_conversation_designs(
    *,
    initial_landlord_message: str | None = None,
    scenario_id: str | None = None,
    conversation_design_ids: list[str] | None = None,
    max_turns: int = 1,
    deterministic_seed: int = 42,
) -> dict:
    design_ids = conversation_design_ids or [VIEWING_FIRST_V1, PHONE_FIRST_V1]
    if not 1 <= len(design_ids) <= 4:
        raise HTTPException(
            status_code=400,
            detail="Select between 1 and 4 conversation designs",
        )

    selected_scenario = get_conversation_scenario(scenario_id)
    if scenario_id and selected_scenario is None:
        raise HTTPException(
            status_code=400,
            detail="Unknown scenario_id",
        )

    custom_message = (initial_landlord_message or "").strip()
    landlord_message = (
        custom_message
        or (selected_scenario.landlord_initial_message if selected_scenario else "")
        or DEFAULT_COMPARE_LANDLORD_MESSAGE
    ).strip()
    if not landlord_message:
        raise HTTPException(
            status_code=400,
            detail="initial_landlord_message is required",
        )
    resolved_scenario_id = (
        selected_scenario.scenario_id if selected_scenario and not custom_message else None
    )
    resolved_scenario_name = (
        selected_scenario.name if selected_scenario and not custom_message else "Custom message"
    )

    return {
        "scenario_id": resolved_scenario_id,
        "scenario_name": resolved_scenario_name,
        "initial_landlord_message": landlord_message,
        "max_turns": max_turns,
        "results": [
            _run_single_design(
                design_id=design_id,
                landlord_message=landlord_message,
                scenario_id=resolved_scenario_id,
                scenario_name=resolved_scenario_name,
                max_turns=max_turns,
                deterministic_seed=deterministic_seed,
            )
            for design_id in design_ids
        ],
    }
