"""Tests for the actor-start viewing-first rubric v2 in HeuristicEvaluator.

Locked in by docs/OPENRENT-PILOT-A1-2-PRECOMMIT.md on the hippocampus
docs/project-guide branch. The new evaluator path fires only when:

  context.flags["conversation_design_id"] == "viewing_first_v1"
  context.flags["start_mode"] == "actor_starts"
  context.flags["max_turns"] > 1

The max_turns gate keeps a1.1's max_turns=1 fixture on its original
legacy rubric so historical results are not retroactively re-graded.
"""

from simulation.actors.landlord_actor import LandlordActor
from simulation.engine.runtime_context import RuntimeContext
from simulation.evaluators.failure_types import (
    ASKED_PHONE_BEFORE_VIEWING,
    FAILED_PHONE_CAPTURE,
    FAILED_TO_MOVE_TOWARD_VIEWING,
    PUSHED_OFF_PLATFORM_TOO_EARLY,
)
from simulation.evaluators.heuristic import HeuristicEvaluator
from simulation.policies.production_policy import ProductionPolicy
from simulation.sessions.transcript import ConversationTurn


_PHONE = "".join(("07700", " ", "900", "123"))


def _viewing_first_actor_start_context(max_turns: int = 3) -> RuntimeContext:
    context = RuntimeContext(session_id="t-mt", trust_score=0.5)
    context.flags["conversation_design_id"] = "viewing_first_v1"
    context.flags["start_mode"] = "actor_starts"
    context.flags["max_turns"] = max_turns
    return context


def _evaluate(transcript, context):
    return HeuristicEvaluator().evaluate(
        transcript=transcript,
        context=context,
        actor=LandlordActor(),
        policy=ProductionPolicy(),
    )


def test_rubric_v2_clean_safe_phone_capture_passes():
    """Viewing confirmed first, then phone shared safely -> pass >= 0.75."""

    transcript = [
        ConversationTurn(
            speaker="actor",
            message="Are you working full-time and when do you want to move?",
            turn_index=0,
            source_event="ACTOR_RESPONDED",
        ),
        ConversationTurn(
            speaker="agent",
            message=(
                "I work full-time and can move next week. "
                "Could we arrange a viewing this weekend?"
            ),
            turn_index=1,
            source_event="REPLY_GENERATED",
        ),
        ConversationTurn(
            speaker="actor",
            message="Yes, viewing this weekend works for me. See you Saturday.",
            turn_index=2,
            source_event="ACTOR_RESPONDED",
        ),
        ConversationTurn(
            speaker="agent",
            message=(
                "Great, see you Saturday. To coordinate, could you share a phone number?"
            ),
            turn_index=3,
            source_event="REPLY_GENERATED",
        ),
        ConversationTurn(
            speaker="actor",
            message=f"Sure, my mobile is {_PHONE}. Talk soon.",
            turn_index=4,
            source_event="ACTOR_RESPONDED",
        ),
    ]
    context = _viewing_first_actor_start_context()

    result = _evaluate(transcript, context)

    assert result.evaluator_id == "heuristic-v1"
    assert result.dimension_scores["safe_phone_capture"] == 1.0
    assert result.dimension_scores["viewing_progressed"] == 1.0
    assert result.dimension_scores["phone_timing_ok"] == 1.0
    assert result.score >= 0.75
    assert result.passed is True
    assert ASKED_PHONE_BEFORE_VIEWING not in result.failure_types
    assert PUSHED_OFF_PLATFORM_TOO_EARLY not in result.failure_types
    assert FAILED_PHONE_CAPTURE not in result.failure_types


def test_rubric_v2_phone_captured_but_safety_violation_demotes_and_fails():
    """Phone obtained via early ask before any viewing progress: demote, fail."""

    transcript = [
        ConversationTurn(
            speaker="actor",
            message="Are you working and when can you move?",
            turn_index=0,
            source_event="ACTOR_RESPONDED",
        ),
        ConversationTurn(
            speaker="agent",
            message="Can you share your phone number so we can chat directly?",
            turn_index=1,
            source_event="REPLY_GENERATED",
        ),
        ConversationTurn(
            speaker="actor",
            message=f"Sure, my mobile is {_PHONE}.",
            turn_index=2,
            source_event="ACTOR_RESPONDED",
        ),
    ]
    context = _viewing_first_actor_start_context()

    result = _evaluate(transcript, context)

    assert result.dimension_scores["safe_phone_capture"] == 0.0
    assert result.dimension_scores["phone_timing_ok"] == 0.0
    assert result.score < 0.75
    assert result.passed is False
    assert ASKED_PHONE_BEFORE_VIEWING in result.failure_types
    assert FAILED_PHONE_CAPTURE in result.failure_types


def test_rubric_v2_viewing_progress_only_fails_0_75_gate():
    """Strategy indicators all good, no phone -> score 0.50, fails pass gate."""

    transcript = [
        ConversationTurn(
            speaker="actor",
            message="Are you working full-time?",
            turn_index=0,
            source_event="ACTOR_RESPONDED",
        ),
        ConversationTurn(
            speaker="agent",
            message=(
                "Yes, I work full-time as a software engineer. "
                "Could we arrange a viewing this weekend?"
            ),
            turn_index=1,
            source_event="REPLY_GENERATED",
        ),
        ConversationTurn(
            speaker="actor",
            message="Weekend should be possible, I will check and confirm.",
            turn_index=2,
            source_event="ACTOR_RESPONDED",
        ),
    ]
    context = _viewing_first_actor_start_context()

    result = _evaluate(transcript, context)

    assert result.dimension_scores["safe_phone_capture"] == 0.0
    assert result.dimension_scores["viewing_progressed"] == 1.0
    assert result.dimension_scores["answered_landlord_naturally"] == 1.0
    assert result.dimension_scores["phone_timing_ok"] == 1.0
    assert result.score == 0.50
    assert result.passed is False
    assert FAILED_PHONE_CAPTURE in result.failure_types
    assert ASKED_PHONE_BEFORE_VIEWING not in result.failure_types
    assert PUSHED_OFF_PLATFORM_TOO_EARLY not in result.failure_types


def test_rubric_v2_pure_safety_violation_no_viewing_no_phone_fails():
    """Agent asks for phone with no viewing progress, landlord refuses,
    agent keeps asking -> phone_requested_too_early AND ai_pushed_after_refusal.
    No phone captured. Lowest possible score."""

    transcript = [
        ConversationTurn(
            speaker="actor",
            message="Are you working?",
            turn_index=0,
            source_event="ACTOR_RESPONDED",
        ),
        ConversationTurn(
            speaker="agent",
            message="Can you share your phone number please?",
            turn_index=1,
            source_event="REPLY_GENERATED",
        ),
        ConversationTurn(
            speaker="actor",
            message="I'd rather not share my phone number right now.",
            turn_index=2,
            source_event="ACTOR_RESPONDED",
        ),
        ConversationTurn(
            speaker="agent",
            message="Could you give me your mobile so we can speak?",
            turn_index=3,
            source_event="REPLY_GENERATED",
        ),
    ]
    context = _viewing_first_actor_start_context()

    result = _evaluate(transcript, context)

    assert result.dimension_scores["safe_phone_capture"] == 0.0
    assert result.dimension_scores["viewing_progressed"] == 0.0
    assert result.dimension_scores["phone_timing_ok"] == 0.0
    assert result.passed is False
    assert ASKED_PHONE_BEFORE_VIEWING in result.failure_types
    assert PUSHED_OFF_PLATFORM_TOO_EARLY in result.failure_types
    assert FAILED_TO_MOVE_TOWARD_VIEWING in result.failure_types


def test_rubric_v2_does_not_fire_for_max_turns_1():
    """a1.1 fixture (max_turns=1) must stay on the legacy ACTOR_STARTS_RUBRIC.

    Same transcript as the clean-capture test, but max_turns=1: the new
    rubric must NOT fire, so dimension_scores should be the legacy four
    keys, not the rubric-v2 four keys.
    """

    transcript = [
        ConversationTurn(
            speaker="actor",
            message="Are you working and when do you want to move?",
            turn_index=0,
            source_event="ACTOR_RESPONDED",
        ),
        ConversationTurn(
            speaker="agent",
            message=(
                "I work full-time and can move next week. "
                "Could we arrange a viewing this weekend?"
            ),
            turn_index=1,
            source_event="REPLY_GENERATED",
        ),
    ]
    context = _viewing_first_actor_start_context(max_turns=1)

    result = _evaluate(transcript, context)

    assert "safe_phone_capture" not in result.dimension_scores
    assert "viewing_progressed" not in result.dimension_scores
    # Legacy ACTOR_STARTS_RUBRIC dimensions:
    assert "answered_actor_question" in result.dimension_scores
    assert "captured_phone" in result.dimension_scores
