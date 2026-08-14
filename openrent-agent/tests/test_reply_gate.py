"""Unit tests for the post-capture reply gate (P1).

Every case here is a scenario from the fleet audit where the worker kept replying
after the landlord's number was already captured (the report-triggering spiral),
or where a naive "stop on captured phone" would have stranded a booked viewing
uncancelled (turning it into a no-show).
"""
from types import SimpleNamespace

from app.ai.reply_gate import post_capture_decision


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
