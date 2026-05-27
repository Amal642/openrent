"""Precommitted falsifier for the orchestrator multi-turn apparatus fix.

These four tests lock in the contract for
`simulation/engine/orchestrator.py` after removing the unconditional
`break` that made max_turns silently equivalent to 1:

  T1 backward compatibility at max_turns=1 (actor_starts).
  T2 max_turns=3 with no terminating signal -> three agent reply pairs.
  T3 max_turns=3 with phone captured on actor's turn-1 response -> one
     agent reply pair (early exit).
  T4 max_turns=3 with viewing confirmed on actor's turn-1 response ->
     one agent reply pair (early exit).

No LLM call is made: `generate_agent_reply` is monkey-patched to drain a
scripted reply queue and emit the REPLY_GENERATED event that
`project_transcript` reads to surface agent turns.
"""

from __future__ import annotations

import uuid

from simulation.actors.base import ActorGoal, ActorProfile, SimulatedActor
from simulation.conversation_state import analyze_conversation_state
from simulation.engine.event_bus import EventBus
from simulation.engine.orchestrator import SimulationOrchestrator
from simulation.engine.runtime_context import RuntimeContext
from simulation.policies.base import AgentPolicy
from simulation.scenarios.base import Scenario
from simulation.sessions.models import AgentResponse


class ScriptedActor(SimulatedActor):
    def __init__(self, *, initial: str, responses: list[str]):
        super().__init__(
            ActorProfile(
                actor_id="scripted-test-actor",
                display_name="Scripted Landlord",
                persona="test",
                tone="neutral",
                goal=ActorGoal(objective="test"),
            )
        )
        self._initial = initial
        self._queue = list(responses)
        self.respond_calls = 0

    def initial_message(self) -> str:
        return self._initial

    def respond(self, context, agent_reply):
        self.respond_calls += 1
        if not self._queue:
            return ""
        return self._queue.pop(0)


def _install_stubs(*, monkeypatch, tmp_path, agent_replies: list[str]):
    """Monkey-patch generate_agent_reply + JSONSessionStore for one test."""

    queue = list(agent_replies)

    def fake_generate_agent_reply(policy, context, event_bus, metrics, *, hippo=None):
        from simulation.engine.session_manager import emit_event

        reply_text = queue.pop(0) if queue else ""
        if reply_text:
            emit_event(
                event_bus,
                context,
                "REPLY_GENERATED",
                {
                    "reply_text": reply_text,
                    "raw_prompt": None,
                    "raw_completion": None,
                    "model": "test",
                    "temperature": 0.0,
                    "valid": True,
                    "error": None,
                    "latency_ms": 0,
                    "token_usage": {},
                },
            )
        agent_response = AgentResponse(
            reply_text=reply_text,
            raw_prompt=None,
            raw_completion=None,
            model="test",
            temperature=0.0,
            valid=bool(reply_text),
            error=None,
        )
        context.last_agent_response = agent_response
        context.memory["last_agent_reply"] = reply_text
        return agent_response

    from simulation.engine import orchestrator as orchestrator_module
    from simulation.sessions import store as session_store_module

    monkeypatch.setattr(
        orchestrator_module,
        "generate_agent_reply",
        fake_generate_agent_reply,
    )

    class TmpStore(session_store_module.JSONSessionStore):
        def __init__(self):
            super().__init__(base_dir=str(tmp_path))

    monkeypatch.setattr(orchestrator_module, "JSONSessionStore", TmpStore)


def _build_orchestrator(*, max_turns: int, actor: SimulatedActor):
    scenario = Scenario(
        scenario_id="apparatus-test",
        title="apparatus",
        description="apparatus multi-turn falsifier",
        success_criteria=[],
        stop_conditions=[],
        start_mode="actor_starts",
        max_turns=max_turns,
    )
    policy = AgentPolicy(
        policy_id="apparatus-test-policy",
        model="test",
        temperature=0.0,
    )
    context = RuntimeContext(session_id=str(uuid.uuid4()))
    return SimulationOrchestrator(
        actor=actor,
        policy=policy,
        scenario=scenario,
        runtime_context=context,
        event_bus=EventBus(),
        initial_message_provider=None,
    )


def _count_speaker(transcript, speaker: str) -> int:
    return sum(1 for turn in transcript if turn.speaker == speaker)


def test_t1_backward_compat_max_turns_one(monkeypatch, tmp_path):
    """max_turns=1 actor_starts: exactly one agent reply pair."""

    _install_stubs(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        agent_replies=[
            "I work full-time and am looking to move. Could we arrange a viewing?",
        ],
    )
    actor = ScriptedActor(
        initial="Are you working full-time and when do you want to move?",
        responses=["Thanks for the info, I'll let you know."],
    )
    orchestrator = _build_orchestrator(max_turns=1, actor=actor)

    session = orchestrator.run()

    assert _count_speaker(session.transcript, "agent") == 1
    assert _count_speaker(session.transcript, "actor") == 2


def test_t2_multi_turn_no_terminating_signal(monkeypatch, tmp_path):
    """max_turns=3 with no phone or confirmation: three agent reply pairs."""

    _install_stubs(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        agent_replies=[
            "I work full-time as a software engineer.",
            "I have been with my current employer for three years.",
            "I would like to discuss viewing options with you.",
        ],
    )
    actor = ScriptedActor(
        initial="Are you employed and ready to discuss the property?",
        responses=[
            "Could you tell me a bit more about your job please?",
            "And how long have you been there?",
            "Got it, thanks for those details.",
        ],
    )
    orchestrator = _build_orchestrator(max_turns=3, actor=actor)

    session = orchestrator.run()

    assert _count_speaker(session.transcript, "agent") == 3
    assert _count_speaker(session.transcript, "actor") == 4

    state = analyze_conversation_state(session.transcript)
    assert state.signals.phone_captured is False
    assert state.signals.viewing_confirmed is False


def test_t3_early_exit_on_phone_captured(monkeypatch, tmp_path):
    """max_turns=3 with a UK mobile in the actor's first response: one pair."""

    _install_stubs(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        agent_replies=[
            "Yes, working full-time. Can we arrange a viewing?",
            "(orchestrator must exit before this is consumed)",
            "(orchestrator must exit before this is consumed)",
        ],
    )
    actor = ScriptedActor(
        initial="Are you employed and ready to move soon?",
        responses=[
            "Sure, my mobile is 07700 900123 if you want to call directly.",
            "(orchestrator must exit before this is consumed)",
            "(orchestrator must exit before this is consumed)",
        ],
    )
    orchestrator = _build_orchestrator(max_turns=3, actor=actor)

    session = orchestrator.run()

    assert _count_speaker(session.transcript, "agent") == 1
    assert _count_speaker(session.transcript, "actor") == 2
    assert actor.respond_calls == 1

    state = analyze_conversation_state(session.transcript)
    assert state.signals.phone_captured is True


def test_t4_early_exit_on_viewing_confirmed(monkeypatch, tmp_path):
    """max_turns=3 with confirmation phrase in actor's first response: one pair."""

    _install_stubs(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        agent_replies=[
            "Working full-time. Could we view this weekend?",
            "(orchestrator must exit before this is consumed)",
            "(orchestrator must exit before this is consumed)",
        ],
    )
    actor = ScriptedActor(
        initial="Are you employed and what is your move timeline?",
        responses=[
            "Yes, viewing this weekend works for me.",
            "(orchestrator must exit before this is consumed)",
            "(orchestrator must exit before this is consumed)",
        ],
    )
    orchestrator = _build_orchestrator(max_turns=3, actor=actor)

    session = orchestrator.run()

    assert _count_speaker(session.transcript, "agent") == 1
    assert _count_speaker(session.transcript, "actor") == 2
    assert actor.respond_calls == 1

    state = analyze_conversation_state(session.transcript)
    assert state.signals.viewing_confirmed is True
