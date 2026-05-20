import uuid

from simulation.engine.deterministic import build_rng
from simulation.engine.event_bus import EventBus
from simulation.engine.orchestrator import SimulationOrchestrator
from simulation.engine.runtime_context import RuntimeContext
from simulation.lab import (
    DEFAULT_ACTOR_ID,
    DEFAULT_POLICY_ID,
    DEFAULT_SCENARIO_ID,
    _resolve_actor,
    _resolve_policy,
    _resolve_scenario,
)
from simulation.templates.initial_message_provider import build_initial_message_provider


def run_simulation(*, deterministic_seed: int = 42, max_turns: int = 1):
    scenario = _resolve_scenario(DEFAULT_SCENARIO_ID, max_turns, "agent_starts")
    actor = _resolve_actor(DEFAULT_ACTOR_ID)
    policy = _resolve_policy(DEFAULT_POLICY_ID)
    initial_message_provider = build_initial_message_provider(source="fixture")
    context = RuntimeContext(
        session_id=str(uuid.uuid4()),
        deterministic_seed=deterministic_seed,
    )
    context.flags["deterministic"] = True
    context.flags["start_mode"] = scenario.start_mode
    context.flags["initial_message_source"] = initial_message_provider.source
    context.metrics["rng_preview"] = build_rng(deterministic_seed).randint(
        1,
        1000,
    )
    orchestrator = SimulationOrchestrator(
        actor=actor,
        policy=policy,
        scenario=scenario,
        runtime_context=context,
        event_bus=EventBus(),
        initial_message_provider=initial_message_provider,
    )
    return orchestrator.run()
