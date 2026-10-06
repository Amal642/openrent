"""Landlord number redacted by OpenRent ("(Number Removed)") - 2026-10-07 fix.

On prod (7 days to 2026-10-07), after a landlord's number was redacted we often
asked for it again ("Could you send it again?"), and sometimes claimed to have
it ("Thanks, I've saved your number" / "I'll pass your number to him now"),
which ends the lead because the landlord never tries again. The pre-cancel step
also blindly asked "could I get your number". The rule now: never re-ask, never
claim to have it, give our WhatsApp instead. Fixture texts are real prod replies.
"""
import asyncio
from types import SimpleNamespace

import pytest

from app.ai import number_redaction as nr
from app.ai import replies
from app.ai.prompts import build_human_renter_reply_prompt, build_reply_prompt
from app.openrent import viewing_lifecycle

MOBILE = "07783129181"
PERSONA = {"persona_name": "Jessica", "persona_partner_name": "Tom", "mobile_number": MOBILE}

REDACTED = {"sender": "landlord", "message": "Sure, my number is (Number Removed) . See you Friday"}
SIGNATURE = {
    "sender": "landlord",
    "message": "Hi Jessica\nYes still available, Saturday 11am is fine.\nThanks\nJas (Number Removed)",
}

BAD_REPLIES = [
    "Thanks, I’ve saved your number. Looking forward to the viewing on Thursday at 6pm.",
    "Thanks, I’ll pass your number to him now. We’ll be in touch soon to confirm the exact time for tomorrow.",
    "Thanks, Jacob. I’ll save your number. See you tomorrow at 5pm.",
    "Thanks, could you please send me your number as well? It’s helpful to have in case I need to get in touch on the day.",
    "Morning Nalaka, all good for 4.30pm today. Could I get that number again but just so it comes through on WhatsApp? Thanks!",
    "I didn’t get your number properly, it came through hidden. Could you send it again? My partner’s number is 07783129181.",
    "Hi Jas, thanks for getting back. Could you please share your number here or on WhatsApp so we can arrange a viewing?",
    "6.30 on Tuesday sounds good, thanks. Could you share your number so my partner can message you on WhatsApp?",
    "Sorry, I wasn’t aware. We’ll message Harshit on that number before we arrive on Friday after 5pm as planned.",
    "I didn’t get that message, thanks for sharing your number. I’ll message you on WhatsApp now so you have mine too.",
    "I’ll call you there tomorrow before the viewing. Can you send me your full number on WhatsApp so I’ve got it exactly?",
]

GOOD_REPLIES = [
    "Thanks, I didn’t get your number properly as it’s blocked here. You can reach me on WhatsApp at 07783129181.",
    "Sunday at 11 works fine. I can’t see your number properly here, but you can reach me on WhatsApp at 07783129181.",
    "My partner’s WhatsApp number is 07783129181, that’s best to message for arranging. Looking forward to Saturday!",
    "Of course, my partner handles all of that, their WhatsApp is 07783129181. They're the best person to reach for the viewing.",
    "I can’t see your number come through, OpenRent seems to be blocking it. Here’s mine for WhatsApp: 07783129181.",
    "Saturday at 3 works, I'll message you if anything changes.",
    "Thanks, your number didn't come through on here.",
    "Tuesday at 6 works for us, see you then.",
    "3pm on Saturday works well. Their WhatsApp is 07783129181 in case you want to message them directly.",
]


# --- detection ---------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "My number is (Number Removed) .",
    "it's ( (Number Removed)",
    "WhatsApp me on + (Number Removed) 3",
    "(number removed)",
    "message me on whatsapp (URL Removed)",
])
def test_blocked_number_detected(text):
    assert nr.text_has_blocked_number(text)


@pytest.mark.parametrize("text", [
    "Viewing Saturday at 11",
    "see the floor plan (URL Removed)",
    "email me (Email Removed)",
    "",
    None,
])
def test_not_a_blocked_number(text):
    assert not nr.text_has_blocked_number(text)


def test_only_landlord_messages_count_as_blocked():
    assert nr.landlord_number_blocked([REDACTED])
    assert not nr.landlord_number_blocked([{"sender": "us", "message": "(Number Removed)"}])
    assert nr.landlord_number_blocked([{"direction": "inbound", "content": "(Number Removed)"}])


def test_redaction_states():
    ours = {"sender": "us", "message": f"My partner's WhatsApp is {MOBILE}."}
    assert nr.redaction_state([{"sender": "landlord", "message": "hi"}], MOBILE) is None
    assert nr.redaction_state([REDACTED], MOBILE) == nr.GIVE
    assert nr.redaction_state([REDACTED, ours], MOBILE) == nr.SHARED
    assert nr.redaction_state([REDACTED, ours, REDACTED], MOBILE) == nr.REMIND
    assert nr.redaction_state([ours, REDACTED], MOBILE) == nr.REMIND
    assert nr.redaction_state([REDACTED], None) == nr.NO_MOBILE


def test_our_number_counts_in_any_format_or_redacted():
    for text in ("whatsapp 07783 129181", "+44 7783 129181", "it's (Number Removed)"):
        msgs = [REDACTED, {"sender": "us", "message": text}]
        assert nr.redaction_state(msgs, MOBILE) == nr.SHARED, text


def test_parse_conversation_keeps_multiline_messages_together():
    text = replies.format_conversation([
        {"sender": "us", "message": "Is it still available?"},
        SIGNATURE,
    ])
    parsed = nr.parse_conversation_text(text)
    assert [m["sender"] for m in parsed] == ["us", "landlord"]
    assert "(Number Removed)" in parsed[1]["message"]
    assert nr.redaction_state(parsed, MOBILE) == nr.GIVE


# --- reply checks --------------------------------------------------------------

@pytest.mark.parametrize("reply", BAD_REPLIES)
def test_real_bad_replies_are_flagged(reply):
    assert nr.reply_redaction_violations(reply)


@pytest.mark.parametrize("reply", GOOD_REPLIES)
def test_real_good_replies_are_not_flagged(reply):
    assert nr.reply_redaction_violations(reply) == []


def test_our_own_fallback_lines_are_clean():
    for i in range(len(nr._GIVEOUT_LINES)):
        line = nr._GIVEOUT_LINES[i].format(mobile=MOBILE)
        assert nr.reply_redaction_violations(line) == []
        assert MOBILE in line
    assert nr.reply_redaction_violations(nr.NO_MOBILE_LINE) == []


def test_giveout_line_varies_by_thread_and_is_stable():
    lines = {nr.redacted_giveout_line(MOBILE, seed=str(t)) for t in range(40)}
    assert len(lines) == len(nr._GIVEOUT_LINES)
    assert nr.redacted_giveout_line(MOBILE, "47011441") == nr.redacted_giveout_line(MOBILE, "47011441")


def test_strip_keeps_the_good_sentences():
    out = nr.strip_violating_sentences(
        "Saturday at 11 works for us. Could you send your number again? See you then!"
    )
    assert out == "Saturday at 11 works for us. See you then!"


# --- number scrubber -----------------------------------------------------------
# Found replaying thread 6398 through the real model: "...WhatsApp at 07783129181.
# 6.30 on the 6th..." was scrubbed to "...WhatsApp at on the 6th...", because the
# approved number and the time matched as one long phone-like run.

@pytest.mark.parametrize("text", [
    "message my partner on WhatsApp at 07783129181. 6.30 on the 6th October works fine",
    "WhatsApp 07783129181 6 30 pm",
    "WhatsApp is +44 7783 129181, see you",
    "WhatsApp is +44 (0)7783 129181.",
    "WhatsApp 07783 129 181!",
    "dial 0044 7783 129181 now",
])
def test_scrubber_keeps_our_number_next_to_times(text):
    from app.ai.validators import remove_unapproved_phone_numbers
    assert remove_unapproved_phone_numbers(text, MOBILE) == text


def test_scrubber_still_strips_other_numbers():
    from app.ai.validators import remove_unapproved_phone_numbers
    assert remove_unapproved_phone_numbers("call 07911 123456 or 07783129181", MOBILE) == "call or 07783129181"
    assert remove_unapproved_phone_numbers("my number 077831291815 is wrong", MOBILE) == "my number is wrong"
    assert remove_unapproved_phone_numbers("call 07911 123456 tomorrow", None) == "call tomorrow"


# --- generate_reply output guard ----------------------------------------------

def _fake_generation(monkeypatch, outputs):
    calls = []

    def fake(conversation, *, model=None, temperature=0.7, prompt_builder=None, retries=3, base_delay=2, allowed_email=None):
        prompt = prompt_builder(conversation) if prompt_builder else ""
        calls.append(prompt)
        text = outputs[min(len(calls) - 1, len(outputs) - 1)]
        return replies.ReplyGenerationResult(
            reply=text, prompt=prompt, completion=text, model="test", temperature=temperature,
            is_valid=True, error=None,
        )

    monkeypatch.setattr(replies, "generate_reply_result", fake)
    monkeypatch.setattr(replies, "latest_landlord_asked_for_phone", lambda m: False)
    monkeypatch.setattr(replies, "_record_handoff_if_shared", lambda *a, **k: None)
    monkeypatch.setenv("HUMAN_REPLY_PROMPT", "all")
    return calls


def _generate(messages, persona=PERSONA, conversation=None, design=None):
    return replies.generate_reply(
        messages, stage="VIEWING_DISCUSSION", persona=persona, thread_id="T-R",
        conversation=conversation, conversation_design_id=design,
    )


def test_reask_is_regenerated_and_our_number_given(monkeypatch):
    clean = f"Friday works. My partner's WhatsApp is {MOBILE}, best to message them there."
    calls = _fake_generation(monkeypatch, ["Friday works. Could you send your number again?", clean])
    reply, error = _generate([REDACTED])
    assert error is None
    assert reply == clean
    assert len(calls) == 2
    assert replies._REDACTION_NUDGE in calls[1]


def test_persistent_false_claim_is_stripped_and_number_appended(monkeypatch):
    bad = "Friday at 6 is great. Thanks, I've saved your number."
    calls = _fake_generation(monkeypatch, [bad])
    reply, error = _generate([REDACTED])
    assert error is None
    assert len(calls) == 3  # original + 2 regenerations
    assert "saved your number" not in reply
    assert reply.startswith("Friday at 6 is great.")
    assert MOBILE in reply
    assert nr.reply_redaction_violations(reply) == []


def test_clean_reply_without_number_gets_our_whatsapp(monkeypatch):
    calls = _fake_generation(monkeypatch, ["Lovely, Friday at 6 works for us."])
    reply, _ = _generate([REDACTED])
    assert len(calls) == 1
    assert reply.startswith("Lovely, Friday at 6 works for us. ")
    assert MOBILE in reply


def test_whole_reply_violating_falls_back_to_giveout_line(monkeypatch):
    _fake_generation(monkeypatch, ["Could you send it again?"])
    reply, error = _generate([REDACTED])
    assert error is None
    assert reply == nr.redacted_giveout_line(MOBILE, seed="T-R")


def test_signature_redaction_also_triggers_giveout(monkeypatch):
    _fake_generation(monkeypatch, ["Saturday 11am is perfect, see you then."])
    reply, _ = _generate([{"sender": "us", "message": "Is it still available?"}, SIGNATURE])
    assert MOBILE in reply


def test_already_shared_is_not_repeated_or_reasked(monkeypatch):
    msgs = [REDACTED, {"sender": "us", "message": f"My partner's WhatsApp is {MOBILE}."},
            {"sender": "landlord", "message": "Great, see you Friday."}]
    _fake_generation(monkeypatch, ["See you Friday! Could you share your number for the day?"])
    reply, _ = _generate(msgs)
    assert reply == "See you Friday!"


def test_redacted_again_after_giveout_reminds(monkeypatch):
    msgs = [{"sender": "us", "message": f"My partner's WhatsApp is {MOBILE}."}, REDACTED]
    _fake_generation(monkeypatch, ["See you Friday."])
    reply, _ = _generate(msgs)
    assert reply.startswith("See you Friday. ") and MOBILE in reply


def test_no_redaction_leaves_reply_untouched(monkeypatch):
    calls = _fake_generation(monkeypatch, ["Could I grab your number for the day?"])
    reply, _ = _generate([{"sender": "landlord", "message": "Friday at 6 works."}])
    assert reply == "Could I grab your number for the day?"
    assert len(calls) == 1


def test_number_already_captured_leaves_reply_untouched(monkeypatch):
    calls = _fake_generation(monkeypatch, ["Thanks, I've saved your number."])
    reply, _ = _generate([REDACTED], conversation=SimpleNamespace(phone_found=True, viewing_datetime=None))
    assert reply == "Thanks, I've saved your number."
    assert len(calls) == 1


def test_no_mobile_account_never_reasks(monkeypatch):
    persona = {"persona_name": "Jessica"}
    _fake_generation(monkeypatch, ["Could you send your number again?"])
    reply, _ = _generate([REDACTED], persona=persona)
    assert reply == nr.NO_MOBILE_LINE


def test_withdrawal_is_not_given_a_number(monkeypatch):
    withdraw = "So sorry, something's come up and I can't make it after all."
    _fake_generation(monkeypatch, [withdraw])
    reply, _ = _generate([
        {"sender": "landlord", "message": "I'm at the property now, my number is (Number Removed)"},
    ])
    assert reply == withdraw


def test_arm_b_legacy_prompt_withholds_number(monkeypatch):
    _fake_generation(monkeypatch, ["Lovely, Friday at 6 works for us."])
    monkeypatch.setenv("HUMAN_REPLY_PROMPT", "0")
    reply, _ = _generate([REDACTED], design="playbook_ab_v1")
    assert MOBILE not in reply
    monkeypatch.setenv("HUMAN_REPLY_PROMPT", "all")
    reply, _ = _generate([REDACTED], design="playbook_ab_v1")
    assert MOBILE in reply


# --- prompt --------------------------------------------------------------------

def _prompt(messages, persona=PERSONA):
    return build_human_renter_reply_prompt(
        conversation=replies.format_conversation(messages), persona=persona,
    )


def test_prompt_gives_exact_instruction_for_signature_redaction():
    prompt = _prompt([{"sender": "us", "message": "Hello"}, SIGNATURE])
    assert "RIGHT NOW" in prompt
    assert "Do NOT ask for their number again" in prompt
    assert MOBILE in prompt


def test_prompt_states_by_thread_history():
    ours = {"sender": "us", "message": f"My partner's WhatsApp is {MOBILE}."}
    assert "blocked it again" in _prompt([ours, REDACTED])
    shared = _prompt([REDACTED, ours])
    assert "already given your partner's WhatsApp" in shared and "RIGHT NOW" not in shared
    assert "carry on arranging things here" in _prompt([REDACTED], persona={"persona_name": "Jessica"})


def test_prompt_without_redaction_has_no_redaction_instruction():
    prompt = _prompt([{"sender": "landlord", "message": "Friday at 6 works."}])
    assert "RIGHT NOW" not in prompt
    assert "Do NOT ask for their number again" not in prompt
    # The general ask rule names the exception, so the model never re-asks.
    assert "never ask for it again" in prompt


def test_build_reply_prompt_routes_to_human_prompt_with_instruction(monkeypatch):
    monkeypatch.setenv("HUMAN_REPLY_PROMPT", "all")
    prompt = build_reply_prompt(replies.format_conversation([REDACTED]), persona=PERSONA)
    assert "RIGHT NOW" in prompt


# --- pre-cancel step -------------------------------------------------------------

def _patch_lifecycle(monkeypatch, conversation, mobile=MOBILE):
    events = {"sent": [], "requested": [], "shared": [], "asked_llm": 0}

    async def send_reply(page, text):
        events["sent"].append(text)
        return True

    def gen_ask(messages, place=None):
        events["asked_llm"] += 1
        return "Could I grab your number for the day?", None

    monkeypatch.setattr(viewing_lifecycle, "send_reply", send_reply)
    monkeypatch.setattr(viewing_lifecycle, "generate_pre_cancel_number_ask", gen_ask)
    monkeypatch.setattr(viewing_lifecycle, "get_conversation_by_thread_id", lambda t: conversation)
    monkeypatch.setattr(viewing_lifecycle, "mark_phone_requested", lambda t: events["requested"].append(t))
    monkeypatch.setattr(viewing_lifecycle, "mark_our_number_shared", lambda t: events["shared"].append(t))
    monkeypatch.setattr(viewing_lifecycle, "ensure_account_persona", lambda _id: {"mobile_number": mobile})
    monkeypatch.setattr(viewing_lifecycle, "save_message", lambda *a: None)
    monkeypatch.setattr(viewing_lifecycle, "record_handoff_intent", lambda *a, **k: None)
    monkeypatch.setattr(viewing_lifecycle, "update_last_processed_message", lambda *a: None)
    return events


def _conv(**kw):
    base = dict(extracted_phone=None, our_number_shared_at=None, landlord_asked_phone_at=None,
                viewing_datetime=None, landlord_attitude="responsive")
    base.update(kw)
    return SimpleNamespace(**base)


def _pre_cancel(messages, account=SimpleNamespace(id=23)):
    return asyncio.run(viewing_lifecycle._send_pre_cancel_number_ask(
        "T-P", messages, messages[-1]["message"], object(), travel_city="Leeds", account=account,
    ))


def test_pre_cancel_gives_whatsapp_instead_of_reasking(monkeypatch):
    events = _patch_lifecycle(monkeypatch, _conv())
    assert _pre_cancel([REDACTED]) is True
    assert events["asked_llm"] == 0
    assert len(events["sent"]) == 1
    assert MOBILE in events["sent"][0]
    assert nr.reply_redaction_violations(events["sent"][0]) == []
    assert events["requested"] == ["T-P"] and events["shared"] == ["T-P"]


def test_pre_cancel_sends_nothing_when_already_shared(monkeypatch):
    from datetime import datetime
    events = _patch_lifecycle(monkeypatch, _conv(our_number_shared_at=datetime.utcnow()))
    assert _pre_cancel([REDACTED]) is False
    assert events["sent"] == [] and events["asked_llm"] == 0
    assert events["requested"] == ["T-P"], "step still marked done so cancel timing is unchanged"


def test_pre_cancel_without_redaction_still_asks(monkeypatch):
    events = _patch_lifecycle(monkeypatch, _conv())
    assert _pre_cancel([{"sender": "landlord", "message": "See you Friday at 6"}]) is True
    assert events["asked_llm"] == 1
    assert events["sent"] == ["Could I grab your number for the day?"]


def test_pre_cancel_skips_when_number_already_captured(monkeypatch):
    events = _patch_lifecycle(monkeypatch, _conv(extracted_phone="07911123456"))
    assert _pre_cancel([REDACTED]) is False
    assert events["sent"] == [] and events["requested"] == []


def test_salvage_after_redaction_explains_the_block(monkeypatch):
    events = _patch_lifecycle(monkeypatch, _conv())
    sent = asyncio.run(viewing_lifecycle._try_giveout_salvage(
        "T-P", _conv(), SimpleNamespace(id=23), [REDACTED], REDACTED["message"], object(),
        require_landlord_asked=False,
    ))
    assert sent is True
    assert events["sent"] == [nr.redacted_giveout_line(MOBILE, seed="T-P")]
