"""Tests for the viewing-cancellation source-of-truth fix.

Regression cover for the no-show bug where a genuinely-confirmed viewing
(viewing_confirmed=True + viewing_datetime) was silently excluded from the
cancellation sweep because its conversation_stage had drifted off VIEWING_BOOKED
(e.g. thread 45975228: stage=VIEWING_DISCUSSION). Cancellation eligibility must
depend ONLY on the authoritative viewing-state fields, never on stage.
"""
import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace

from app.db.repository import viewing_cancellation_due
from scripts import process_viewing_reminders


NOW = datetime(2026, 8, 24, 12, 0, 0)


def _conv(**overrides):
    base = dict(
        viewing_datetime=NOW + timedelta(hours=4),
        viewing_confirmed=True,
        viewing_cancelled=False,
        cancellation_sent_at=None,
        handoff_completed_at=None,
        cancel_target_hours=4.3,
        # deliberately a non-booked stage — the predicate must ignore it entirely
        conversation_stage="VIEWING_DISCUSSION",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


# ---- viewing_cancellation_due predicate ----

def test_due_when_confirmed_and_in_window_regardless_of_stage():
    # The 45975228 shape: confirmed viewing, in window, stage NOT VIEWING_BOOKED.
    assert viewing_cancellation_due(_conv(), NOW) is True


def test_stage_is_irrelevant_even_when_booked():
    assert viewing_cancellation_due(_conv(conversation_stage="VIEWING_BOOKED"), NOW) is True


def test_not_due_when_not_confirmed():
    assert viewing_cancellation_due(_conv(viewing_confirmed=False), NOW) is False


def test_not_due_when_already_cancelled():
    assert viewing_cancellation_due(_conv(viewing_cancelled=True), NOW) is False


def test_not_due_when_cancellation_already_sent():
    assert viewing_cancellation_due(_conv(cancellation_sent_at=NOW), NOW) is False


def test_not_due_when_handoff_complete():
    assert viewing_cancellation_due(_conv(handoff_completed_at=NOW), NOW) is False


def test_not_due_when_viewing_in_past():
    assert viewing_cancellation_due(_conv(viewing_datetime=NOW - timedelta(hours=1)), NOW) is False


def test_not_due_when_before_window():
    # Viewing 10h away, target 4.3h -> cancel_at is 5.7h in the future.
    assert viewing_cancellation_due(
        _conv(viewing_datetime=NOW + timedelta(hours=10)), NOW
    ) is False


def test_not_due_without_viewing_datetime():
    assert viewing_cancellation_due(_conv(viewing_datetime=None), NOW) is False


def test_none_conversation_is_safe():
    assert viewing_cancellation_due(None, NOW) is False


def test_default_target_hours_when_unset():
    # cancel_target_hours falls back to 4.0; viewing 3h away -> cancel_at 1h ago -> due.
    assert viewing_cancellation_due(
        _conv(cancel_target_hours=None, viewing_datetime=NOW + timedelta(hours=3)), NOW
    ) is True


# ---- reminder sweep no longer gated on VIEWING_BOOKED stage ----

def test_reminder_cancels_confirmed_viewing_with_discussion_stage(monkeypatch):
    """A confirmed viewing whose stage is VIEWING_DISCUSSION must still be
    withdrawn by the sweep (the exact 45975228 no-show condition). Here the
    number is already captured, so the sweep proceeds straight to cancellation."""
    from datetime import datetime as _dt

    account = SimpleNamespace(id=1, email="tenant@example.test")
    cancelled = []

    conv = SimpleNamespace(
        viewing_datetime=_dt.utcnow() + timedelta(hours=3),  # in-window future
        viewing_confirmed=True,
        viewing_cancelled=False,
        cancellation_sent_at=None,
        handoff_completed_at=None,
        cancel_target_hours=4.3,
        extracted_phone="447700900123",  # captured -> safe_to_cancel
        phone_requested_at=None,
        our_number_shared_at="already",  # salvage no-ops
        landlord_asked_phone_at=None,
        landlord_attitude="responsive",
        conversation_stage="VIEWING_DISCUSSION",  # NOT booked — must not matter
    )

    monkeypatch.setattr(
        process_viewing_reminders,
        "get_due_viewing_cancellations",
        lambda account_id: [
            {
                "thread_id": "thread-drifted",
                "viewing_datetime": conv.viewing_datetime,
                "viewing_confirmed": True,
            }
        ],
    )
    monkeypatch.setattr(process_viewing_reminders, "claim_conversation", lambda *_a: True)
    monkeypatch.setattr(process_viewing_reminders, "get_conversation_by_thread_id", lambda _t: conv)
    monkeypatch.setattr(
        process_viewing_reminders, "get_automatic_cancellation_block_reason", lambda _t: None
    )
    monkeypatch.setattr(process_viewing_reminders, "get_latest_landlord_message", lambda _m: "hi")

    async def noop_async(*_a, **_k):
        return None

    async def extract_conversation(_page):
        return []

    async def cancel(thread_id, *a, **k):
        cancelled.append(thread_id)
        return True

    async def salvage(*a, **k):
        return False

    monkeypatch.setattr(process_viewing_reminders, "open_thread", noop_async)
    monkeypatch.setattr(process_viewing_reminders, "extract_conversation", extract_conversation)
    monkeypatch.setattr(process_viewing_reminders, "_cancel_viewing_and_handoff", cancel)
    monkeypatch.setattr(process_viewing_reminders, "_try_giveout_salvage", salvage)
    monkeypatch.setattr(process_viewing_reminders, "release_conversation_claim", lambda *a: None)
    monkeypatch.setattr(process_viewing_reminders, "random_sleep", noop_async)

    asyncio.run(
        process_viewing_reminders.process_account_viewing_reminders(
            account, object(), worker_id="worker-1"
        )
    )

    assert cancelled == ["thread-drifted"]
