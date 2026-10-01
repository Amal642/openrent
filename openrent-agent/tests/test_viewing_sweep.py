"""Decision-tree coverage for the enriched Phase-2 viewing-withdrawal sweep
(process_account_viewing_reminders), now the single owner of viewing withdrawal:
give-out salvage -> pre-cancel number-ask (2-step) -> cancellation, with an
imminent-viewing override. Verifies each branch fires the right action.
"""
import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace

from scripts import process_viewing_reminders as pvr


def _run(monkeypatch, conv, block_reason=None):
    """Run the sweep for a single due viewing and return which action fired."""
    calls = {"cancel": [], "salvage": [], "ask": [], "released": []}
    account = SimpleNamespace(id=1, email="t@example.test")

    monkeypatch.setattr(
        pvr, "get_due_viewing_cancellations",
        lambda account_id: [{
            "thread_id": "t1",
            "viewing_datetime": conv.viewing_datetime,
            "viewing_confirmed": conv.viewing_confirmed,
        }],
    )
    monkeypatch.setattr(pvr, "claim_conversation", lambda *_a: True)
    monkeypatch.setattr(pvr, "get_conversation_by_thread_id", lambda _t: conv)
    monkeypatch.setattr(pvr, "get_automatic_cancellation_block_reason", lambda _t: block_reason)
    monkeypatch.setattr(pvr, "get_travel_city", lambda _t: "Leeds")
    monkeypatch.setattr(pvr, "get_latest_landlord_message", lambda _m: "hi")

    async def noop_async(*_a, **_k):
        return None

    async def extract_conversation(_p):
        return []

    async def cancel(*a, **k):
        calls["cancel"].append(a)
        return True

    def salvage_factory(returns):
        async def salvage(*a, **k):
            calls["salvage"].append(a)
            return returns
        return salvage

    async def ask(*a, **k):
        calls["ask"].append(a)
        return True

    monkeypatch.setattr(pvr, "open_thread", noop_async)
    monkeypatch.setattr(pvr, "extract_conversation", extract_conversation)
    monkeypatch.setattr(pvr, "random_sleep", noop_async)
    monkeypatch.setattr(pvr, "_cancel_viewing_and_handoff", cancel)
    monkeypatch.setattr(pvr, "_try_giveout_salvage", salvage_factory(getattr(conv, "_salvage_returns", False)))
    monkeypatch.setattr(pvr, "_send_pre_cancel_number_ask", ask)
    monkeypatch.setattr(pvr, "release_conversation_claim",
                        lambda t, o: calls["released"].append((t, o)))

    asyncio.run(pvr.process_account_viewing_reminders(account, object(), worker_id="w1"))
    return calls


def _conv(**over):
    base = dict(
        viewing_datetime=datetime.utcnow() + timedelta(hours=3),  # in 3-5h window
        viewing_confirmed=True,
        viewing_cancelled=False,
        cancellation_sent_at=None,
        handoff_completed_at=None,
        cancel_target_hours=4.3,
        extracted_phone=None,
        phone_requested_at=None,
        our_number_shared_at=None,
        landlord_asked_phone_at=None,
        landlord_attitude="responsive",
    )
    base.update(over)
    return SimpleNamespace(**base)


def test_phone_captured_cancels(monkeypatch):
    # Number already captured -> safe_to_cancel -> salvage(no-op, number exists) -> cancel.
    calls = _run(monkeypatch, _conv(extracted_phone="447700900000"))
    assert len(calls["cancel"]) == 1
    assert calls["ask"] == []
    assert calls["released"] == [("t1", "w1")]


def test_not_yet_asked_sends_number_ask(monkeypatch):
    # No phone, not imminent, never asked -> pre-cancel number-ask (2-step), no cancel.
    calls = _run(monkeypatch, _conv())
    assert len(calls["ask"]) == 1
    assert calls["cancel"] == []


def test_asked_long_ago_cancels(monkeypatch):
    # Asked >4h ago and landlord responded (no block) -> cancel.
    calls = _run(monkeypatch, _conv(phone_requested_at=datetime.utcnow() - timedelta(hours=5)))
    assert len(calls["cancel"]) == 1
    assert calls["ask"] == []


def test_imminent_viewing_cancels_without_ask_age(monkeypatch):
    # Viewing 1h away -> imminent override -> cancel now even though never asked.
    calls = _run(monkeypatch, _conv(viewing_datetime=datetime.utcnow() + timedelta(hours=1)))
    assert len(calls["cancel"]) == 1
    assert calls["ask"] == []


def test_salvage_defers_cancel(monkeypatch):
    # Salvage sends the give-out -> defer cancel one run (no cancel this run).
    conv = _conv(extracted_phone="447700900000")
    conv._salvage_returns = True
    calls = _run(monkeypatch, conv)
    assert len(calls["salvage"]) == 1
    assert calls["cancel"] == []


def test_blocked_does_nothing(monkeypatch):
    calls = _run(monkeypatch, _conv(phone_requested_at=datetime.utcnow() - timedelta(hours=5)),
                 block_reason="awaiting_phone_request_response")
    assert calls["cancel"] == []
    assert calls["ask"] == []
    assert calls["salvage"] == []


def test_not_due_on_refresh_skips(monkeypatch):
    # Candidate query returned it, but the fresh conversation is already cancelled.
    calls = _run(monkeypatch, _conv(viewing_cancelled=True))
    assert calls["cancel"] == [] and calls["ask"] == [] and calls["salvage"] == []
    assert calls["released"] == [("t1", "w1")]


# --- Hard deadline + salvage timing (2026-10-01 audit: 28 viewings passed while
# "awaiting phone-request response", ~15 after a give-out deferred the cancel). ---

def test_blocked_but_at_deadline_cancels(monkeypatch):
    conv = _conv(
        viewing_datetime=datetime.utcnow() + timedelta(hours=1.0),
        phone_requested_at=datetime.utcnow() - timedelta(hours=2),
    )
    calls = _run(monkeypatch, conv, block_reason="awaiting_phone_request_response")
    assert len(calls["cancel"]) == 1
    assert calls["salvage"] == [] and calls["ask"] == []


def test_blocked_with_time_left_still_waits(monkeypatch):
    conv = _conv(
        viewing_datetime=datetime.utcnow() + timedelta(hours=3.5),
        phone_requested_at=datetime.utcnow() - timedelta(hours=1),
    )
    calls = _run(monkeypatch, conv, block_reason="awaiting_phone_request_response")
    assert calls["cancel"] == [] and calls["salvage"] == [] and calls["ask"] == []


def test_no_giveout_when_too_close_to_defer(monkeypatch):
    # 2h away: a give-out would push the cancel ~1h later, too close -> cancel now.
    conv = _conv(viewing_datetime=datetime.utcnow() + timedelta(hours=2.0))
    conv._salvage_returns = True
    calls = _run(monkeypatch, conv)
    assert calls["salvage"] == []
    assert len(calls["cancel"]) == 1


def test_giveout_still_offered_with_time_left(monkeypatch):
    conv = _conv(
        viewing_datetime=datetime.utcnow() + timedelta(hours=3.5),
        phone_requested_at=datetime.utcnow() - timedelta(hours=5),
    )
    conv._salvage_returns = True
    calls = _run(monkeypatch, conv)
    assert len(calls["salvage"]) == 1
    assert calls["cancel"] == []


def test_never_asked_at_deadline_cancels_instead_of_asking(monkeypatch):
    calls = _run(monkeypatch, _conv(viewing_datetime=datetime.utcnow() + timedelta(hours=0.8)))
    assert len(calls["cancel"]) == 1
    assert calls["ask"] == []
