"""Guard that blocks re-tiering an account with live conversations.

Regression for the persona-contradiction incident (accounts 29 & 31, 2026-08-15):
re-tiering an account that had already sent openings under a different persona
made its replies contradict the opening in the same thread.
"""
from app.services.retier_guard import is_open_thread, TERMINAL_STAGES, CLOSED_STATUSES


def test_active_thread_is_open():
    assert is_open_thread("AI_REPLIED", "VIEWING_DISCUSSION") is True


def test_opening_only_thread_is_open():
    # Opening sent, no landlord reply yet — still a risk: a later reply contradicts.
    assert is_open_thread("INITIAL_MESSAGE_SENT", "INITIAL_MESSAGE_SENT") is True


def test_phone_acquired_but_still_repliable_is_open():
    assert is_open_thread("PHONE_ACQUIRED", "VIEWING_DISCUSSION") is True


def test_terminal_stage_is_closed():
    for stage in TERMINAL_STAGES:
        assert is_open_thread("AI_REPLIED", stage) is False


def test_closed_or_reply_disabled_status_is_closed():
    for status in CLOSED_STATUSES:
        assert is_open_thread(status, "VIEWING_DISCUSSION") is False


def test_handoff_complete_not_counted():
    assert is_open_thread("PHONE_ACQUIRED", "HANDOFF_COMPLETE") is False
