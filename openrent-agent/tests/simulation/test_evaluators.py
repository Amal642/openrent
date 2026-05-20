from simulation.actors.landlord_actor import LandlordActor
from simulation.engine.runtime_context import RuntimeContext
from simulation.evaluators.heuristic import HeuristicEvaluator
from simulation.policies.production_policy import ProductionPolicy
from simulation.sessions.transcript import ConversationTurn


SIMULATED_PHONE = "".join(("07", "123", "456", "789"))


def test_heuristic_evaluator_passes_when_phone_is_captured():
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
                "Could you share your phone number please?"
            ),
            turn_index=1,
            source_event="REPLY_GENERATED",
        ),
    ]
    context = RuntimeContext(session_id="session-1", trust_score=0.8)
    context.extracted_entities["phone"] = SIMULATED_PHONE

    result = HeuristicEvaluator().evaluate(
        transcript=transcript,
        context=context,
        actor=LandlordActor(),
        policy=ProductionPolicy(),
    )

    assert result.passed is True
    assert result.score >= 0.75


def test_heuristic_evaluator_scores_agent_starts_opener_and_followup():
    transcript = [
        ConversationTurn(
            speaker="agent",
            message=(
                "Hi, I'm Mary, I work in IT. My husband and I really like your "
                "property and were hoping to have a quick call before booking a viewing. "
                "Could you please share your phone number?"
            ),
            turn_index=0,
            source_event="AGENT_INITIAL_MESSAGE_SENT",
        ),
        ConversationTurn(
            speaker="actor",
            message="Before I share my number, can you confirm your work situation and when you want to move?",
            turn_index=1,
            source_event="ACTOR_RESPONDED",
        ),
        ConversationTurn(
            speaker="agent",
            message=(
                "I work full-time and can move next week. "
                "Could you share your phone number please?"
            ),
            turn_index=1,
            source_event="REPLY_GENERATED",
        ),
    ]
    context = RuntimeContext(session_id="session-2", trust_score=0.8)
    context.flags["start_mode"] = "agent_starts"
    context.memory["initial_agent_message"] = transcript[0].message
    context.extracted_entities["phone"] = SIMULATED_PHONE

    result = HeuristicEvaluator().evaluate(
        transcript=transcript,
        context=context,
        actor=LandlordActor(),
        policy=ProductionPolicy(),
    )

    assert result.passed is True
    assert result.dimension_scores["initial_message_emitted"] == 1.0
    assert result.dimension_scores["opener_realism"] == 1.0
