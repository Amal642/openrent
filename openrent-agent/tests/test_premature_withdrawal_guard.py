"""Premature-withdrawal guard (2026-10-01 audit).

The model backed out of viewings on a plain same-day confirmation ("just
confirming your viewing this evening at 6pm" -> "something's come up, I won't
be able to make it"), skipping the timed sweep's ask-for-number / give-out
steps. generate_reply now regenerates such replies with a keep-the-viewing
nudge, unless the landlord says the viewing is happening right now.
"""
from app.ai import replies

WITHDRAW = "Morning, something’s come up so I won’t be able to make it this evening after all. Sorry!"
CONFIRM = "Lovely, still on for 6pm, see you then!"


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
    # Keep the deterministic phone-share shortcut out of the way.
    monkeypatch.setattr(replies, "latest_landlord_asked_for_phone", lambda m: False)
    return calls


def _generate(messages):
    return replies.generate_reply(
        messages, stage="VIEWING_BOOKED", persona={"persona_name": "Jessica"}, thread_id="T-W"
    )


def test_same_day_confirmation_does_not_withdraw(monkeypatch):
    calls = _fake_generation(monkeypatch, [WITHDRAW, CONFIRM])
    reply, error = _generate([
        {"sender": "landlord", "message": "Good morning Jessica, just confirming your viewing for this evening at 6pm"},
    ])
    assert error is None
    assert reply == CONFIRM
    assert len(calls) == 2
    assert replies._KEEP_VIEWING_NUDGE in calls[1]
    assert replies._KEEP_VIEWING_NUDGE not in calls[0]


def test_landlord_waiting_now_may_withdraw(monkeypatch):
    calls = _fake_generation(monkeypatch, [WITHDRAW, CONFIRM])
    reply, error = _generate([
        {"sender": "landlord", "message": "I'm outside the property now, are you nearly here?"},
    ])
    assert error is None
    assert reply == WITHDRAW
    assert len(calls) == 1


def test_guard_never_turns_into_an_error(monkeypatch):
    calls = _fake_generation(monkeypatch, [WITHDRAW])  # every attempt withdraws
    reply, error = _generate([{"sender": "landlord", "message": "Still on for tomorrow?"}])
    assert error is None
    assert reply == WITHDRAW  # exhausted: falls back to the original, logged
    assert len(calls) == 3


def test_normal_reply_is_untouched(monkeypatch):
    calls = _fake_generation(monkeypatch, [CONFIRM])
    reply, error = _generate([{"sender": "landlord", "message": "See you at 6"}])
    assert error is None and reply == CONFIRM and len(calls) == 1


def test_withdrawal_detector():
    assert replies.is_viewing_withdrawal(WITHDRAW)
    assert replies.is_viewing_withdrawal("Sorry, I'll need to cancel the viewing.")
    assert replies.is_viewing_withdrawal("I can't make it today")
    assert not replies.is_viewing_withdrawal(CONFIRM)
    assert not replies.is_viewing_withdrawal("I cancelled my other viewing so I'm free")
    assert not replies.is_viewing_withdrawal("Can you make it at 6 instead?")
