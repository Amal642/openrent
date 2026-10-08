"""Landlords phoning/texting our WhatsApp-only give-out number (2026-10-08).

Cases are real landlord messages from prod. Policy agreed with the user: the
give-out stays as is; only when the landlord brings up calling or texting do we
steer them to a WhatsApp message, in the persona's voice, never saying
"WhatsApp only"."""
from datetime import datetime, timedelta, timezone

import pytest

from app.ai import call_intent as ci
from app.ai.prompts import build_human_renter_reply_prompt
from app.ai.reply_timing import reply_hold_remaining_seconds

MOBILE = "07783129181"
GAVE = [
    {"sender": "landlord", "message": "Saturday at 4pm works, could you share a number?"},
    {"sender": "us", "message": "Saturday at 4 works. My partner's WhatsApp is 07783129181, best to message him there."},
]


def _state(landlord_text, history=GAVE, mobile=MOBILE):
    return ci.call_state(history + [{"sender": "landlord", "message": landlord_text}], mobile)


@pytest.mark.parametrize("text", [
    "Called twice , not able to connect",
    "I texted your phone number called no answer",
    "Hi, I tried to call but the number did not ring. I will be at the property for 6:30pm.",
    "Your number does not work. I've messaged and tried calling.",
    "Hi Claire, i tried calling the number you provided, it does not connnect.",
    "I texted the number and not heard back?",
    "We tried calling you this morning on whatsapp but no one picked up.",
    "Calls not connecting this number",
])
def test_tried_and_failed(text):
    assert _state(text) == ci.TRIED


@pytest.mark.parametrize("text", [
    "I can see your number and will call you tomorrow. Do you have a time preference?",
    "I'll give you a call in a moment with my number.",
    "Can I give him a ring?",
    "I will text you a reminder on Thursday. Thanks, Lisa",
    "My daughter will call you this evening.",
    "I would like to speak over the phone first",
])
def test_will_call(text):
    assert _state(text) == ci.WILL_CALL


@pytest.mark.parametrize("text", [
    "You didn't answer my question about pets",
    "I'll call the agent and let you know",
    "The lettings team will call them back",
    "Thanks, I'll message him on WhatsApp now",
    "no answer yet on the move in date, will confirm",
    "Great, see you Saturday",
])
def test_not_a_call_to_us(text):
    assert _state(text) is None


def test_nothing_before_we_gave_a_number_unless_they_ask_for_one_to_call():
    history = [{"sender": "us", "message": "Hi, is the flat still available?"}]
    assert _state("I'll call you tomorrow", history=history) is None
    assert _state("Can I have your number so I can call you?", history=history) == ci.ASK_TO_CALL


def test_only_new_landlord_messages_count():
    history = GAVE + [
        {"sender": "landlord", "message": "Tried calling, no answer"},
        {"sender": "us", "message": "Really sorry, he must have been caught up."},
    ]
    assert _state("Ok see you Saturday", history=history) is None


def test_instructions_steer_to_whatsapp_message_without_saying_whatsapp_only():
    tried = ci.prompt_instruction(ci.TRIED, MOBILE)
    will = ci.prompt_instruction(ci.WILL_CALL, MOBILE)
    assert "caught up" in tried and "WhatsApp message" in tried
    assert "can't always pick up" in will
    for text in (tried, will):
        assert "Never say the number is \"WhatsApp only\"" in text
        assert "never say you look forward to their call" in text


@pytest.mark.parametrize("reply", [
    "Looking forward to your call.",
    "I'll call you at 5.30pm tomorrow then.",
    "4pm today works fine, I'll be ready to take the call then.",
    "Thanks, I'll look out for your call tomorrow.",
    "You can call him any time.",
    "Speak soon on the phone!",
])
def test_guard_flags_replies_that_accept_a_call(reply):
    assert ci.reply_agrees_to_call(reply)


@pytest.mark.parametrize("reply", [
    "Really sorry, he must have been caught up. If you send him a quick WhatsApp message he'll reply as soon as he sees it.",
    "Feel free to text him on WhatsApp.",
    "I'll pick up the keys at 5",
    "I will answer your questions below.",
    "Saturday at 4 works for us.",
])
def test_guard_leaves_normal_replies_alone(reply):
    assert not ci.reply_agrees_to_call(reply)


def test_strip_keeps_the_rest_of_the_reply():
    assert ci.strip_call_sentences("Saturday works. Looking forward to your call.") == "Saturday works."


def test_prompt_gets_instruction_only_when_calling_comes_up():
    persona = {"persona_name": "Claire", "persona_partner_name": "Marcus", "mobile_number": MOBILE}
    base = "LANDLORD: Saturday at 4pm works\nUS: Saturday works. My partner's WhatsApp is 07783129181."
    with_call = build_human_renter_reply_prompt(conversation=base + "\nLANDLORD: Tried calling, no answer", persona=persona)
    without = build_human_renter_reply_prompt(conversation=base + "\nLANDLORD: Great see you then", persona=persona)
    assert "RIGHT NOW: the landlord says they tried to call or text" in with_call
    assert "tried to call or text" not in without and "will call or text" not in without


def test_failed_call_skips_the_human_reply_delay():
    now = datetime(2026, 10, 8, 12, 0)
    ts = str(int((now - timedelta(seconds=10)).replace(tzinfo=timezone.utc).timestamp()))
    msgs = [dict(m, timestamp=ts) for m in GAVE] + [
        {"sender": "landlord", "message": "Just tried to call, no answer", "timestamp": ts}
    ]
    assert reply_hold_remaining_seconds(msgs, "t1", now=now) == 0.0
    calm = [dict(m, timestamp=ts) for m in GAVE] + [
        {"sender": "landlord", "message": "Great, see you Saturday", "timestamp": ts}
    ]
    assert reply_hold_remaining_seconds(calm, "t1", now=now) > 0


def test_landlord_waiting_at_the_property_now_is_left_to_the_withdraw_rule():
    waiting = "I am at the property waiting for you. I have called you on the number you provided but it did not connect."
    assert _state(waiting) is None
    assert _state("I tried to call but it didn't ring. I will be at the property for 6:30pm.") == ci.TRIED


def test_examples_use_partner_name_and_rotate_per_thread():
    a = ci.prompt_instruction(ci.TRIED, MOBILE, partner_name="Laura", seed="thread-a")
    b = ci.prompt_instruction(ci.TRIED, MOBILE, partner_name="Laura", seed="thread-zz")
    assert "Laura" in a and "right pronoun for Laura" in a
    assert {line.format(p="Laura") in a for line in ci._TRIED_LINES} == {True, False}
    assert a != b or len(ci._TRIED_LINES) == 1


def test_own_number_threads_speak_in_first_person():
    own = [{"sender": "us", "message": "You can reach me on WhatsApp at 07599390221."}]
    assert ci.number_is_partners(own, None, "Michael") is False
    assert ci.number_is_partners(GAVE, MOBILE, "Marcus") is True
    text = ci.prompt_instruction(ci.TRIED, MOBILE, partner_name="Michael", seed="x", partners=False)
    assert "your own" in text and "Michael" not in text
