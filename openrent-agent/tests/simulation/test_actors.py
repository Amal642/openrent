from simulation.actors.landlord_actor import LandlordActor
from simulation.engine.runtime_context import RuntimeContext


def test_landlord_actor_shares_phone_when_screening_is_answered():
    actor = LandlordActor()
    context = RuntimeContext(session_id="session-1")

    reply = (
        "I work full-time and I can move next week. "
        "Could you share your phone number please?"
    )

    actor_response = actor.respond(context, reply)

    assert "07123456789" in actor_response
    assert context.goal_progress["phone_shared"] is True

