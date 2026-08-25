"""Unit tests for the post-capture reply gate (P1).

Every case here is a scenario from the fleet audit where the worker kept replying
after the landlord's number was already captured (the report-triggering spiral),
or where a naive "stop on captured phone" would have stranded a booked viewing
uncancelled (turning it into a no-show).
"""
from types import SimpleNamespace

from app.ai.reply_gate import post_capture_decision, landlord_wants_video_call


def _conv(**kw):
    base = dict(
        extracted_phone=None,
        viewing_confirmed=False,
        viewing_cancelled=False,
        handoff_completed_at=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_no_phone_proceeds_with_normal_reply():
    assert post_capture_decision(_conv()) is None


def test_missing_conversation_proceeds():
    assert post_capture_decision(None) is None


def test_empty_phone_string_is_not_a_capture():
    assert post_capture_decision(_conv(extracted_phone="")) is None


def test_captured_without_viewing_is_terminal():
    # The common case: number obtained during discussion, no viewing booked.
    assert post_capture_decision(_conv(extracted_phone="07123456789")) == "terminal"


def test_captured_with_open_booking_stays_pending_cancel():
    # Must NOT terminalise — the booked viewing still needs cancelling, else no-show.
    assert (
        post_capture_decision(
            _conv(extracted_phone="07123456789", viewing_confirmed=True)
        )
        == "pending_cancel"
    )


def test_captured_after_cancellation_is_terminal():
    assert (
        post_capture_decision(
            _conv(
                extracted_phone="07123456789",
                viewing_confirmed=True,
                viewing_cancelled=True,
            )
        )
        == "terminal"
    )


def test_captured_after_handoff_is_terminal():
    assert (
        post_capture_decision(
            _conv(
                extracted_phone="07123456789",
                viewing_confirmed=True,
                handoff_completed_at="2026-08-13T10:00:00",
            )
        )
        == "terminal"
    )


# --- landlord_wants_video_call ------------------------------------------------
def _ll(text):
    return [{"sender": "landlord", "message": text}]


def test_video_call_request_detected():
    assert landlord_wants_video_call(
        _ll("I'd like a quick video call with both of you before an in-person viewing.")
    )


def test_google_meet_link_detected():
    assert landlord_wants_video_call(_ll("Let's use this google meet link: https://meet.google.com/abc"))


def test_show_remotely_detected():
    assert landlord_wants_video_call(_ll("I can show you the flat remotely during the call."))


def test_zoom_and_teams_detected():
    assert landlord_wants_video_call(_ll("Happy to do a Zoom first."))
    assert landlord_wants_video_call(_ll("Shall we set up a Teams meeting?"))


def test_our_own_message_is_ignored():
    # Same phrase but from us must NOT trigger (would self-trigger every run).
    assert not landlord_wants_video_call([{"sender": "us", "message": "Can we do a video call?"}])


def test_scans_whole_thread_not_just_latest():
    msgs = [
        {"sender": "landlord", "message": "Happy to arrange a quick video call first."},
        {"sender": "us", "message": "Sure, when suits?"},
        {"sender": "landlord", "message": "Let me know a couple of times to reschedule."},
    ]
    assert landlord_wants_video_call(msgs)


def test_ordinary_viewing_message_not_flagged():
    assert not landlord_wants_video_call(_ll("Happy to arrange a viewing this weekend, what time suits?"))


def test_plain_phone_call_arrival_not_flagged():
    assert not landlord_wants_video_call(_ll("Give me a ring when you arrive and I'll buzz you in."))


def test_empty_and_malformed_safe():
    assert not landlord_wants_video_call([])
    assert not landlord_wants_video_call(None)
    assert not landlord_wants_video_call(["not a dict", 123])
