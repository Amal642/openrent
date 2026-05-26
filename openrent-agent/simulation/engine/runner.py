import os
import uuid

from simulation.engine.deterministic import build_rng
from simulation.engine.event_bus import EventBus
from simulation.engine.hippo_hooks import (
    DEFAULT_RECALL_GOAL,
    HippoSession,
    HippoSessionMeta,
)
from simulation.engine.orchestrator import SimulationOrchestrator
from simulation.engine.runtime_context import RuntimeContext
from simulation.conversation_designs import default_simulation_persona
from simulation.lab import (
    DEFAULT_ACTOR_ID,
    DEFAULT_POLICY_ID,
    DEFAULT_SCENARIO_ID,
    _resolve_actor,
    _resolve_policy,
    _resolve_scenario,
)
from simulation.templates.initial_message_provider import build_initial_message_provider


def run_simulation(
    *,
    deterministic_seed: int = 42,
    max_turns: int = 1,
    hippo_memory: bool = False,
    hippo_snap: str | None = None,
    hippo_server_js: str | None = None,
    hippo_project_id: str = "openrent-sim",
    hippo_thread_id: str | None = None,
    hippo_participant_id: str | None = None,
    hippo_account_id: str | None = None,
    hippo_property: dict | None = None,
    hippo_stage: str | None = None,
    hippo_strategy: str | None = None,
    hippo_goal: str = DEFAULT_RECALL_GOAL,
    hippo_tags: tuple[str, ...] = (),
):
    """Run one deterministic simulation session.

    `hippo_memory=False` is the regression-safe default: no MCP traffic,
    no behaviour change vs. the pre-7a engine. When `True`, a memory-kit
    MCP client is opened for the lifetime of this call and torn down
    on exit; recall + ingest hooks fire inside the orchestrator.
    """

    scenario = _resolve_scenario(DEFAULT_SCENARIO_ID, max_turns, "agent_starts")
    actor = _resolve_actor(DEFAULT_ACTOR_ID)
    persona = default_simulation_persona()
    policy = _resolve_policy(DEFAULT_POLICY_ID)
    initial_message_provider = build_initial_message_provider(
        source="fixture", persona=persona
    )
    session_id = str(uuid.uuid4())
    context = RuntimeContext(
        session_id=session_id,
        deterministic_seed=deterministic_seed,
    )
    context.flags["deterministic"] = True
    context.flags["start_mode"] = scenario.start_mode
    context.flags["initial_message_source"] = initial_message_provider.source
    context.flags["hippo_memory"] = "on" if hippo_memory else "off"
    context.metrics["rng_preview"] = build_rng(deterministic_seed).randint(
        1,
        1000,
    )

    hippo_session = None
    if hippo_memory:
        hippo_session = _build_hippo_session(
            server_js=hippo_server_js,
            storage=hippo_snap,
            project_id=hippo_project_id,
            thread_id=hippo_thread_id or session_id,
            participant_id=hippo_participant_id,
            account_id=hippo_account_id,
            property_=hippo_property,
            stage=hippo_stage,
            strategy=hippo_strategy,
            goal=hippo_goal,
            tags=hippo_tags,
        )

    try:
        orchestrator = SimulationOrchestrator(
            actor=actor,
            policy=policy,
            scenario=scenario,
            runtime_context=context,
            event_bus=EventBus(),
            initial_message_provider=initial_message_provider,
            hippo=hippo_session,
        )
        return orchestrator.run()
    finally:
        if hippo_session is not None:
            hippo_session.close()


def _build_hippo_session(
    *,
    server_js: str | None,
    storage: str | None,
    project_id: str,
    thread_id: str,
    participant_id: str | None,
    account_id: str | None,
    property_: dict | None,
    stage: str | None,
    strategy: str | None,
    goal: str,
    tags: tuple[str, ...],
) -> HippoSession:
    from app.ai.memory.hippo_client import HippoOutreachClient

    resolved_server_js = server_js or os.environ.get("HIPPO_STDIO_JS")
    if not resolved_server_js:
        raise RuntimeError(
            "hippo_memory=on requires --hippo-server-js or the "
            "HIPPO_STDIO_JS environment variable to point at the "
            "memory-kit-mcp stdio.js entrypoint."
        )
    client = HippoOutreachClient(
        server_js=resolved_server_js,
        storage=storage or ":memory:",
        project_id=project_id,
    )
    meta = HippoSessionMeta(
        thread_id=thread_id,
        participant_id=participant_id,
        account_id=account_id,
        property=property_,
        stage=stage,
        strategy=strategy,
        goal=goal,
        tags=tuple(tags),
    )
    return HippoSession(client=client, meta=meta)
