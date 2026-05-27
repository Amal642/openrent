import os

import pytest

from simulation.actors.llm_landlord_actor import (
    LlmLandlordActor,
    PERSONA_REGISTRY,
    SIMULATED_LANDLORD_PHONE,
)
from simulation.engine.runtime_context import RuntimeContext


def _stub_completion(text: str):
    """Build the smallest object shape _extract_completion_text accepts."""

    return {"choices": [{"message": {"content": text}}]}


@pytest.mark.parametrize("persona", sorted(PERSONA_REGISTRY))
def test_persona_prompt_mandates_phone_share_format(persona):
    """P1.1 Part 2 invariant: each persona's system prompt must require
    phone-share replies to contain the phone number + an agreement word
    + a view/time word. String match only; no LLM calls.
    """

    prompt = PERSONA_REGISTRY[persona]["system_prompt"]
    assert SIMULATED_LANDLORD_PHONE in prompt
    assert "agreement word" in prompt
    assert "view/time word" in prompt


@pytest.mark.parametrize("persona", sorted(PERSONA_REGISTRY))
def test_initial_message_returns_persona_specific_opener(persona):
    actor = LlmLandlordActor(
        persona=persona, completion_create=lambda **_: _stub_completion("noop"),
    )
    opener = actor.initial_message()
    assert opener == PERSONA_REGISTRY[persona]["initial_message"]


def test_respond_uses_stubbed_completion_and_routes_text():
    captured: dict = {}

    def fake_completion(**kwargs):
        captured.update(kwargs)
        return _stub_completion(
            f"Yes, that works. You can call me on {SIMULATED_LANDLORD_PHONE} "
            "this evening to confirm the viewing."
        )

    actor = LlmLandlordActor(
        persona="cooperative", completion_create=fake_completion,
    )
    actor.initial_message()  # seed history
    context = RuntimeContext(session_id="test")

    reply = actor.respond(context, "I work full-time and want to move next month.")

    assert SIMULATED_LANDLORD_PHONE in reply
    assert captured["model"] == "gpt-4.1-mini"
    # Cooperative persona's default_temperature is 0.5 (Q3-locked).
    assert captured["temperature"] == 0.5
    # System prompt + opener (assistant) + agent reply (user) = 3 messages
    assert len(captured["messages"]) == 3
    assert captured["messages"][0]["role"] == "system"


def test_brusque_persona_default_temperature_is_lowered():
    """Q4-amendment-1: Brusque defaults to temp 0.2 to keep the
    LLM closer to its strict refusal instructions.
    """

    captured: dict = {}

    def fake_completion(**kwargs):
        captured.update(kwargs)
        return _stub_completion("Need work and move date first.")

    actor = LlmLandlordActor(
        persona="brusque", completion_create=fake_completion,
    )
    actor.initial_message()
    actor.respond(RuntimeContext(session_id="brusque-temp"), "Hello.")

    assert captured["temperature"] == 0.2


def test_respond_flips_phone_shared_when_output_contains_phone():
    actor = LlmLandlordActor(
        persona="cooperative",
        completion_create=lambda **_: _stub_completion(
            f"Yes, call me on {SIMULATED_LANDLORD_PHONE} this evening."
        ),
    )
    actor.initial_message()
    context = RuntimeContext(session_id="phone")

    actor.respond(context, "Can I have your phone number?")

    assert context.goal_progress["phone_shared"] is True


def test_respond_flips_offered_time_when_output_offers_a_time():
    actor = LlmLandlordActor(
        persona="cooperative",
        completion_create=lambda **_: _stub_completion(
            "How about Saturday at 2pm?"
        ),
    )
    actor.initial_message()
    context = RuntimeContext(session_id="offer")

    actor.respond(context, "Can we arrange a viewing?")

    assert context.goal_progress.get("offered_time") is True
    assert "phone_shared" not in context.goal_progress


def test_respond_keeps_history_across_calls():
    seen_messages: list[list[dict]] = []

    def fake_completion(**kwargs):
        seen_messages.append(list(kwargs["messages"]))
        return _stub_completion("ok")

    actor = LlmLandlordActor(
        persona="suspicious", completion_create=fake_completion,
    )
    actor.initial_message()
    context = RuntimeContext(session_id="hist")

    actor.respond(context, "I work full-time.")
    actor.respond(context, "I want to move next month, can we arrange a viewing?")

    # Second respond sees system + opener + agent#1 + landlord#1 + agent#2 = 5
    assert len(seen_messages[1]) == 5
    roles = [m["role"] for m in seen_messages[1]]
    assert roles == ["system", "assistant", "user", "assistant", "user"]


def test_unknown_persona_raises():
    with pytest.raises(ValueError, match="unknown persona"):
        LlmLandlordActor(persona="aggressive")


@pytest.mark.skipif(
    not os.getenv("OPENRENT_LIVE_LLM_TESTS"),
    reason="set OPENRENT_LIVE_LLM_TESTS=1 to run live OpenAI calls",
)
@pytest.mark.parametrize("persona", sorted(PERSONA_REGISTRY))
def test_live_phone_share_satisfies_predicates(persona):
    """P1.1 Part 3 hint: a single live call per persona, only run when
    explicitly enabled. The smoke step (precommit step 3) does the
    statistical version of this across N=5; this test is the smallest
    sanity check that the prompt elicits a predicate-satisfying reply
    on a single deterministic scenario.
    """

    actor = LlmLandlordActor(persona=persona, temperature=0.3)
    actor.initial_message()
    context = RuntimeContext(session_id=f"live-{persona}")

    reply = actor.respond(
        context,
        "I work full-time as a teacher and I can move next month. "
        "Saturday at 2pm works perfectly for me — could you share your "
        "phone number so I can call to confirm?",
    )

    lowered = reply.lower()
    agreement_words = ["yes", "that works", "works", "ok", "okay"]
    view_words = ["viewing", "evening", "weekend", "tomorrow", "tonight"]
    assert SIMULATED_LANDLORD_PHONE in reply
    assert any(w in lowered for w in agreement_words)
    assert any(w in lowered for w in view_words)
