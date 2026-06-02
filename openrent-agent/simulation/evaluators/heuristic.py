import time

from simulation.conversation_state import analyze_conversation_state
from simulation.evaluators.base import BaseEvaluator
from simulation.evaluators.failure_types import (
    ASKED_PHONE_BEFORE_VIEWING,
    FAILED_PHONE_CAPTURE,
    FAILED_TO_MOVE_TOWARD_VIEWING,
    INCOHERENT_FOLLOWUP,
    IGNORED_QUESTION,
    LOW_TRUST,
    MISSING_INITIAL_MESSAGE,
    PUSHED_OFF_PLATFORM_TOO_EARLY,
    UNREALISTIC_OPENER,
)
from simulation.evaluators.rubric import AGENT_STARTS_RUBRIC, ACTOR_STARTS_RUBRIC
from simulation.sessions.models import EvaluationResult


VIEWING_PROGRESS_DESIGNS = {
    "viewing_first_v1",
    "corpus_number_capture_v1",
}


class HeuristicEvaluator(BaseEvaluator):
    evaluator_id = "heuristic-v1"

    def _evaluate_viewing_first(
        self,
        *,
        transcript,
        context,
        actor,
        started_at,
    ):
        conversation_state = analyze_conversation_state(
            transcript,
            context.flags.get("conversation_design_id"),
        )
        signals = conversation_state.signals
        agent_turns = [turn for turn in transcript if turn.speaker == "agent"]
        actor_turns = [turn for turn in transcript if turn.speaker == "actor"]
        initial_message = (context.memory.get("initial_agent_message") or "").strip()
        initial_text = initial_message.lower()
        initial_asks_phone = "phone" in initial_text or "number" in initial_text
        first_actor_text = actor_turns[0].message.lower() if actor_turns else ""
        viewing_progressed = (
            signals.viewing_requested
            or signals.viewing_time_offered
            or signals.viewing_confirmed
        )
        answered_screening = (
            not signals.screening_questions_asked or signals.screening_answered
        )
        phone_captured = signals.phone_captured or "phone" in context.extracted_entities
        phone_timing_ok = not (
            signals.phone_requested_too_early or signals.ai_pushed_after_refusal
        )
        captured_after_viewing = phone_captured and signals.viewing_confirmed

        failure_types = []
        if not initial_message:
            failure_types.append(MISSING_INITIAL_MESSAGE)
        if initial_asks_phone or signals.phone_requested_too_early:
            failure_types.append(ASKED_PHONE_BEFORE_VIEWING)
        if first_actor_text and not answered_screening:
            failure_types.append(IGNORED_QUESTION)
        if agent_turns and not viewing_progressed:
            failure_types.append(FAILED_TO_MOVE_TOWARD_VIEWING)
        if signals.ai_pushed_after_refusal:
            failure_types.append(PUSHED_OFF_PLATFORM_TOO_EARLY)

        dimension_scores = {
            "initial_message_emitted": 1.0 if initial_message else 0.0,
            "opener_delayed_phone": 0.0 if initial_asks_phone else 1.0,
            "answered_landlord_naturally": 1.0 if answered_screening else 0.0,
            "viewing_progress": 1.0 if viewing_progressed else 0.0,
            "phone_timing": 1.0 if phone_timing_ok else 0.0,
            "captured_phone": 1.0 if captured_after_viewing else 0.0,
        }
        score = (
            dimension_scores["initial_message_emitted"] * 0.15
            + dimension_scores["opener_delayed_phone"] * 0.2
            + dimension_scores["answered_landlord_naturally"] * 0.2
            + dimension_scores["viewing_progress"] * 0.25
            + dimension_scores["phone_timing"] * 0.2
        )

        return EvaluationResult(
            evaluator_id=self.evaluator_id,
            score=round(score, 4),
            passed=score >= 0.75,
            dimension_scores=dimension_scores,
            failure_types=failure_types,
            rationale=(
                "Viewing-first evaluation based on viewing progress, natural "
                "screening answers, and delayed phone capture."
            ),
            evaluation_timing_ms=int(
                (time.perf_counter() - started_at) * 1000
            ),
            conversation_state=conversation_state.to_dict(),
        )

    def evaluate(self, transcript, context, actor, policy):
        started_at = time.perf_counter()
        conversation_state = analyze_conversation_state(
            transcript,
            context.flags.get("conversation_design_id"),
        )
        if (
            context.flags.get("conversation_design_id") in VIEWING_PROGRESS_DESIGNS
            and context.flags.get("start_mode") == "agent_starts"
        ):
            return self._evaluate_viewing_first(
                transcript=transcript,
                context=context,
                actor=actor,
                started_at=started_at,
            )
        agent_turns = [turn for turn in transcript if turn.speaker == "agent"]
        actor_turns = [turn for turn in transcript if turn.speaker == "actor"]
        latest_agent_text = agent_turns[-1].message.lower() if agent_turns else ""
        first_actor_text = actor_turns[0].message.lower() if actor_turns else ""
        start_mode = context.flags.get("start_mode", "actor_starts")

        answered_question = (
            "work" in latest_agent_text or "employ" in latest_agent_text
        ) and (
            "move" in latest_agent_text
            or "available" in latest_agent_text
            or "next week" in latest_agent_text
        )
        asked_for_phone = (
            "phone" in latest_agent_text or "number" in latest_agent_text
        )
        phone_captured = "phone" in context.extracted_entities
        trust_ok = context.trust_score >= actor.profile.goal.trust_threshold

        if start_mode == "agent_starts":
            initial_message = (context.memory.get("initial_agent_message") or "").strip()
            initial_message_text = initial_message.lower()
            latest_followup_turn = next(
                (
                    turn
                    for turn in reversed(agent_turns)
                    if turn.source_event == "REPLY_GENERATED"
                ),
                None,
            )
            latest_followup_text = (
                latest_followup_turn.message.lower()
                if latest_followup_turn is not None
                else ""
            )
            trust_ok = phone_captured or (
                context.trust_score >= actor.profile.goal.trust_threshold
            )
            opener_realism = bool(initial_message) and all(
                token in initial_message_text
                for token in ["property", "viewing"]
            ) and (
                "phone" in initial_message_text or "number" in initial_message_text
            ) and "@" not in initial_message_text and "ai" not in initial_message_text
            followup_coherent = bool(latest_followup_text) and answered_question and (
                "phone" in latest_followup_text or "number" in latest_followup_text
            )

            failure_types = []
            if not initial_message:
                failure_types.append(MISSING_INITIAL_MESSAGE)
            if initial_message and not opener_realism:
                failure_types.append(UNREALISTIC_OPENER)
            if first_actor_text and not answered_question:
                failure_types.append(IGNORED_QUESTION)
            if first_actor_text and not followup_coherent:
                failure_types.append(INCOHERENT_FOLLOWUP)
            if latest_followup_text and not phone_captured:
                failure_types.append(FAILED_PHONE_CAPTURE)
            if not trust_ok:
                failure_types.append(LOW_TRUST)

            dimension_scores = {
                "initial_message_emitted": 1.0 if initial_message else 0.0,
                "opener_realism": 1.0 if opener_realism else 0.0,
                "followup_answered_actor_question": 1.0 if answered_question else 0.0,
                "followup_phone_progress": 1.0 if followup_coherent else 0.0,
                "captured_phone": 1.0 if phone_captured else 0.0,
                "trust_progress": 1.0 if trust_ok else 0.0,
            }
            rubric = AGENT_STARTS_RUBRIC
        else:
            failure_types = []
            if not answered_question and first_actor_text:
                failure_types.append(IGNORED_QUESTION)
            if asked_for_phone and not phone_captured:
                failure_types.append(FAILED_PHONE_CAPTURE)
            if not trust_ok:
                failure_types.append(LOW_TRUST)

            dimension_scores = {
                "answered_actor_question": 1.0 if answered_question else 0.0,
                "asked_for_phone": 1.0 if asked_for_phone else 0.0,
                "captured_phone": 1.0 if phone_captured else 0.0,
                "trust_progress": 1.0 if trust_ok else 0.0,
            }
            rubric = ACTOR_STARTS_RUBRIC

        score = 0.0
        for key, weight in rubric.items():
            score += dimension_scores.get(key, 0.0) * weight

        return EvaluationResult(
            evaluator_id=self.evaluator_id,
            score=round(score, 4),
            passed=score >= 0.75,
            dimension_scores=dimension_scores,
            failure_types=failure_types,
            rationale=(
                "Heuristic evaluation based on answer quality, phone "
                "progress, and trust."
            ),
            evaluation_timing_ms=int(
                (time.perf_counter() - started_at) * 1000
            ),
            conversation_state=conversation_state.to_dict(),
        )
