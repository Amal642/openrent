"""Burst-aware landlord-intent detection — the Sandra/Claire lost-lead fix.

Frozen from the real thread 46001479 (acct 22, persona Claire, landlord Sandra R.):
the landlord asked for our number in one message and proposed a viewing in the
next; the old latest-only detectors saw only the viewing message and missed the
ask, so we cancelled instead of sharing our give-out.
"""
from app.ai.conversation_memory import (
    unanswered_landlord_messages,
    latest_landlord_asked_for_phone,
    latest_landlord_hesitant_about_phone,
    detect_screening_questions,
)
from app.ai.personas import landlord_asked_for_phone


def _ll(t):
    return {"sender": "landlord", "message": t}


def _us(t):
    return {"sender": "us", "message": t}


SANDRA_BURST = [
    _us("Hi Sandra, could you please share your phone number so I can reach you on the day?"),
    _ll("Yes send me the number and I will call you."),
    _ll("Claire can you come for a viewing this afternoon at 12.05?"),
]


def test_sandra_burst_phone_ask_now_detected():
    assert latest_landlord_asked_for_phone(SANDRA_BURST) is True


def test_the_final_message_alone_is_not_a_phone_ask():
    # documents why latest-only failed: the last message is not an ask
    assert landlord_asked_for_phone("Claire can you come for a viewing this afternoon at 12.05?") is False


def test_unanswered_burst_is_messages_since_our_last_reply():
    assert [m["message"] for m in unanswered_landlord_messages(SANDRA_BURST)] == [
        "Yes send me the number and I will call you.",
        "Claire can you come for a viewing this afternoon at 12.05?",
    ]


def test_burst_stops_at_our_reply_so_answered_asks_do_not_relinger():
    msgs = [_ll("Send me your number please"), _us("Sure, one sec"), _ll("what time works?")]
    assert [m["message"] for m in unanswered_landlord_messages(msgs)] == ["what time works?"]
    assert latest_landlord_asked_for_phone(msgs) is False


def test_fallback_when_last_message_is_ours():
    msgs = [_ll("send me your number"), _us("ok")]
    assert [m["message"] for m in unanswered_landlord_messages(msgs)] == ["send me your number"]


def test_screening_aggregates_across_the_burst():
    msgs = [_us("hi"), _ll("What is your occupation?"), _ll("And your move in date?")]
    topics = detect_screening_questions(msgs)
    assert "employment" in topics and "move_date" in topics


def test_single_message_behaviour_unchanged():
    # last landlord message preceded by ours -> burst is just that message
    msgs = [_us("hi"), _ll("Can you send me your number?")]
    assert latest_landlord_asked_for_phone(msgs) is True
    assert [m["message"] for m in unanswered_landlord_messages(msgs)] == ["Can you send me your number?"]


def test_empty_and_none_safe():
    assert unanswered_landlord_messages([]) == []
    assert unanswered_landlord_messages(None) == []
    assert latest_landlord_asked_for_phone([]) is False
    assert latest_landlord_hesitant_about_phone(None) is False
    assert detect_screening_questions([]) == []
