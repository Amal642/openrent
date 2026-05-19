import re
import time

from app.ai.replies import generate_reply_result
from simulation.evaluators.heuristic import HeuristicEvaluator
from simulation.observability.metrics import MetricsCollector
from simulation.observability.token_usage import usage_from_result
from simulation.replay.formatter import format_replay
from simulation.sessions.event_models import SimulationEvent
from simulation.sessions.models import AgentResponse, SimulationSession
from simulation.sessions.store import JSONSessionStore
from simulation.sessions.transcript import project_transcript


PHONE_PATTERN = re.compile(r"(?:\+?44\s?7\d{3}|\b07\d{3})\s?\d{3}\s?\d{3}\b")


def emit_event(event_bus, context, event_type: str, payload: dict):
    from simulation.engine import orchestrator as orchestrator_module

    event_bus.emit(
        SimulationEvent(
            event_type=event_type,
            turn_index=context.current_turn,
            timestamp=orchestrator_module.build_event_timestamp(),
            payload=payload,
        )
    )


def build_agent_response(result, generation_latency_ms: int) -> AgentResponse:
    return AgentResponse(
        reply_text=result.reply,
        raw_prompt=result.prompt,
        raw_completion=result.completion,
        model=result.model,
        temperature=result.temperature,
        valid=result.is_valid,
        error=result.error,
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
        total_tokens=result.total_tokens,
        latency_ms=result.latency_ms or generation_latency_ms,
    )


def update_context_from_actor_message(context, actor_message: str) -> dict:
    context.last_actor_response = actor_message
    context.memory["last_actor_message"] = actor_message

    payload = {
        "trust_score": context.trust_score,
        "goal_progress": dict(context.goal_progress),
        "extracted_entities": dict(context.extracted_entities),
    }

    phone_match = PHONE_PATTERN.search(actor_message or "")
    if phone_match:
        phone = re.sub(r"\s+", "", phone_match.group(0))
        context.extracted_entities["phone"] = phone
        payload["extracted_entities"] = dict(context.extracted_entities)
        payload["phone_detected"] = phone

    return payload


def update_context_from_agent_message(context, agent_message: str, *, key: str) -> dict:
    context.memory[key] = agent_message
    return {
        "trust_score": context.trust_score,
        "goal_progress": dict(context.goal_progress),
        "extracted_entities": dict(context.extracted_entities),
        key: agent_message,
    }


def generate_agent_reply(policy, context, event_bus, metrics):
    prompt_messages = project_transcript(event_bus.events)
    started_at = time.perf_counter()
    result = generate_reply_result(
        prompt_messages,
        model=policy.model,
        temperature=policy.temperature,
        prompt_builder=policy.build_prompt,
    )
    generation_latency_ms = int((time.perf_counter() - started_at) * 1000)
    metrics.record_generation(result, generation_latency_ms)

    agent_response = build_agent_response(result, generation_latency_ms)
    context.last_agent_response = agent_response
    emit_event(
        event_bus,
        context,
        "REPLY_GENERATED",
        {
            "reply_text": agent_response.reply_text,
            "raw_prompt": agent_response.raw_prompt,
            "raw_completion": agent_response.raw_completion,
            "model": agent_response.model,
            "temperature": agent_response.temperature,
            "valid": agent_response.valid,
            "error": agent_response.error,
            "latency_ms": agent_response.latency_ms,
            "token_usage": usage_from_result(agent_response),
        },
    )
    context.memory["last_agent_reply"] = agent_response.reply_text
    emit_event(
        event_bus,
        context,
        "MEMORY_UPDATED",
        {
            "trust_score": context.trust_score,
            "goal_progress": dict(context.goal_progress),
            "extracted_entities": dict(context.extracted_entities),
            "last_agent_reply": agent_response.reply_text,
        },
    )
    return agent_response


def evaluate_session(actor, policy, context, event_bus, metrics):
    evaluator = HeuristicEvaluator()
    transcript = project_transcript(event_bus.events)
    evaluation = evaluator.evaluate(
        transcript=transcript,
        context=context,
        actor=actor,
        policy=policy,
    )
    metrics.record_evaluation(evaluation.evaluation_timing_ms)
    emit_event(
        event_bus,
        context,
        "EVALUATION_COMPLETED",
        {
            "score": evaluation.score,
            "passed": evaluation.passed,
            "failure_types": evaluation.failure_types,
        },
    )
    return evaluation


def build_session(
    *,
    mode: str,
    actor,
    policy,
    scenario,
    context,
    event_bus,
    evaluation,
    observability,
):
    transcript = project_transcript(event_bus.events)
    replay_output = format_replay(
        event_bus.events,
        transcript,
        evaluation,
    )
    return SimulationSession(
        session_id=context.session_id,
        mode=mode,
        start_mode=scenario.start_mode,
        initial_message_source=context.flags.get("initial_message_source"),
        initial_message=context.memory.get("initial_agent_message"),
        scenario_id=scenario.scenario_id,
        actor_id=actor.profile.actor_id,
        policy_id=policy.policy_id,
        deterministic_seed=context.deterministic_seed,
        max_turns=scenario.max_turns,
        transcript=transcript,
        events=event_bus.events,
        evaluation=evaluation,
        runtime_context=context.snapshot(),
        replay_output=replay_output,
        observability=observability,
    )


def finalize_session(
    *,
    mode: str,
    actor,
    policy,
    scenario,
    context,
    event_bus,
    metrics,
    session_started,
    store=None,
):
    evaluation = evaluate_session(actor, policy, context, event_bus, metrics)
    run_duration_ms = int((time.perf_counter() - session_started) * 1000)
    if context.flags.get("deterministic"):
        run_duration_ms = (
            metrics._generation_latency_ms + metrics._evaluation_timing_ms
        )
    observability = metrics.finalize(run_duration_ms)
    session = build_session(
        mode=mode,
        actor=actor,
        policy=policy,
        scenario=scenario,
        context=context,
        event_bus=event_bus,
        evaluation=evaluation,
        observability=observability,
    )
    emit_event(
        event_bus,
        context,
        "SESSION_FINISHED",
        {
            "session_id": session.session_id,
            "run_duration_ms": session.observability["run_duration_ms"],
            "mode": mode,
        },
    )
    session.events = event_bus.events
    session.transcript = project_transcript(session.events)
    session.replay_output = format_replay(
        session.events,
        session.transcript,
        session.evaluation,
    )
    (store or JSONSessionStore()).save(session)
    return session


def metrics_from_session(session: dict | None) -> MetricsCollector:
    runtime_context = (session or {}).get("runtime_context") or {}
    metrics = MetricsCollector(dict(runtime_context.get("metrics") or {}))
    observability = (session or {}).get("observability") or {}
    metrics._prompt_tokens = observability.get("prompt_tokens", 0)
    metrics._completion_tokens = observability.get("completion_tokens", 0)
    metrics._total_tokens = observability.get("total_tokens", 0)
    metrics._generation_latency_ms = observability.get(
        "generation_latency_ms",
        0,
    )
    metrics._evaluation_timing_ms = observability.get(
        "evaluation_timing_ms",
        0,
    )
    return metrics
