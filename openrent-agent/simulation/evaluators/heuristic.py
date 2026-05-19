import time

from simulation.evaluators.base import BaseEvaluator
from simulation.evaluators.failure_types import (
    FAILED_PHONE_CAPTURE,
    INCOHERENT_FOLLOWUP,
    IGNORED_QUESTION,
    LOW_TRUST,
    MISSING_INITIAL_MESSAGE,
    UNREALISTIC_OPENER,
)
from simulation.evaluators.rubric import AGENT_STARTS_RUBRIC, ACTOR_STARTS_RUBRIC
from simulation.sessions.models import EvaluationResult


class HeuristicEvaluator(BaseEvaluator):
    evaluator_id = "heuristic-v1"

    def evaluate(self, transcript, context, actor, policy):
        started_at = time.perf_counter()
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
        )
