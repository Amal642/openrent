from simulation.actors.landlord_actor import LandlordActor, SIMULATED_LANDLORD_PHONE
from simulation.conversation_state import TIME_PATTERN, analyze_conversation_state
from simulation.engine.runtime_context import RuntimeContext


def test_landlord_actor_shares_phone_when_screening_is_answered():
    actor = LandlordActor()
    context = RuntimeContext(session_id="session-1")

    reply = (
        "I work full-time and I can move next week. "
        "Could you share your phone number please?"
    )

    actor_response = actor.respond(context, reply)

    assert SIMULATED_LANDLORD_PHONE in actor_response
    assert context.goal_progress["phone_shared"] is True


def test_landlord_actor_proactive_offer_fires_on_turn_two():
    actor = LandlordActor()
    context = RuntimeContext(session_id="a4-branch5")
    context.current_turn = 2

    agent_reply = (
        "I work full-time and we can move next month. "
        "Can we arrange a viewing?"
    )

    actor_response = actor.respond(context, agent_reply)

    assert context.goal_progress.get("offered_time") is True
    assert "Saturday at 2pm" in actor_response
    assert TIME_PATTERN.search(actor_response) is not None


def test_landlord_actor_proactive_offer_flips_viewing_time_offered_signal():
    actor = LandlordActor()
    context = RuntimeContext(session_id="a4-signal")
    context.current_turn = 2

    agent_reply = (
        "I work full-time and we can move next month. "
        "Can we arrange a viewing?"
    )
    actor_response = actor.respond(context, agent_reply)

    transcript = [
        {"speaker": "actor", "message": "Hi, are you working and when do you want to move?"},
        {"speaker": "agent", "message": agent_reply},
        {"speaker": "actor", "message": actor_response},
    ]
    state = analyze_conversation_state(transcript, "viewing_first_v1")

    assert state.signals.viewing_time_offered is True


def test_landlord_actor_proactive_offer_is_one_shot_per_trial():
    actor = LandlordActor()
    context = RuntimeContext(session_id="a4-oneshot")
    context.current_turn = 2
    context.goal_progress["offered_time"] = True

    agent_reply = (
        "I work full-time and we can move next month. "
        "Can we arrange a viewing?"
    )

    actor_response = actor.respond(context, agent_reply)

    assert "Saturday at 2pm" not in actor_response


def test_landlord_actor_shares_phone_after_offered_time_without_re_stated_screening():
    actor = LandlordActor()
    context = RuntimeContext(session_id="a4-q3-relaxed")
    context.goal_progress["offered_time"] = True

    agent_reply = "Saturday at 2pm sounds great! Can I have your phone?"

    actor_response = actor.respond(context, agent_reply)

    assert SIMULATED_LANDLORD_PHONE in actor_response
    assert context.goal_progress["phone_shared"] is True


def test_landlord_actor_does_not_offer_on_turn_one():
    actor = LandlordActor()
    context = RuntimeContext(session_id="a4-turn-one-guard")
    context.current_turn = 1

    agent_reply = (
        "I work full-time and we can move next month. "
        "Can we arrange a viewing?"
    )

    actor_response = actor.respond(context, agent_reply)

    assert "Saturday at 2pm" not in actor_response
    assert context.goal_progress.get("offered_time", False) is False
