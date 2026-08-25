import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace

from scripts import process_replies, process_viewing_reminders
from app.openrent import viewing_lifecycle


def test_reply_time_cancellation_is_blocked_while_phone_request_unanswered(
    monkeypatch,
):
    # The withdrawal helpers now live in app.openrent.viewing_lifecycle and
    # resolve their dependencies in that module's namespace, so patch there.
    # process_replies still re-exports _cancel_viewing_and_handoff (same object).
    sent = []

    monkeypatch.setattr(
        viewing_lifecycle,
        "get_automatic_cancellation_block_reason",
        lambda _thread_id: "awaiting_phone_request_response",
    )

    async def send_reply(_page, message):
        sent.append(message)
        return True

    monkeypatch.setattr(viewing_lifecycle, "send_reply", send_reply)

    result = asyncio.run(
        process_replies._cancel_viewing_and_handoff(
            "thread-waiting",
            [],
            None,
            object(),
        )
    )

    assert result is False
    assert sent == []


def test_reminder_worker_blocks_unanswered_phone_request(monkeypatch):
    """An unanswered phone request blocks the sweep: no salvage, no ask, no cancel."""
    account = SimpleNamespace(id=1, email="tenant@example.test")
    released = []
    cancel_calls, salvage_calls, ask_calls = [], [], []

    future_in_window = datetime.utcnow() + timedelta(hours=3)  # inside 3-5h window
    conv = SimpleNamespace(
        viewing_datetime=future_in_window,
        viewing_confirmed=True,
        viewing_cancelled=False,
        cancellation_sent_at=None,
        handoff_completed_at=None,
        cancel_target_hours=4.3,
        extracted_phone=None,
        phone_requested_at=datetime.utcnow() - timedelta(hours=1),  # asked, <4h ago
    )

    monkeypatch.setattr(
        process_viewing_reminders,
        "get_due_viewing_cancellations",
        lambda account_id: [
            {
                "thread_id": "thread-waiting",
                "viewing_datetime": future_in_window,
                "viewing_confirmed": True,
            }
        ],
    )
    monkeypatch.setattr(process_viewing_reminders, "claim_conversation", lambda *_a: True)
    monkeypatch.setattr(
        process_viewing_reminders, "get_conversation_by_thread_id", lambda _t: conv
    )
    monkeypatch.setattr(
        process_viewing_reminders,
        "get_automatic_cancellation_block_reason",
        lambda _t: "awaiting_phone_request_response",
    )

    async def noop_async(*_a, **_k):
        return None

    async def extract_conversation(_page):
        return []

    async def cancel(*a, **k):
        cancel_calls.append(a)
        return True

    async def salvage(*a, **k):
        salvage_calls.append(a)
        return False

    async def ask(*a, **k):
        ask_calls.append(a)
        return True

    monkeypatch.setattr(process_viewing_reminders, "open_thread", noop_async)
    monkeypatch.setattr(process_viewing_reminders, "extract_conversation", extract_conversation)
    monkeypatch.setattr(process_viewing_reminders, "get_latest_landlord_message", lambda _m: "hi")
    monkeypatch.setattr(process_viewing_reminders, "_cancel_viewing_and_handoff", cancel)
    monkeypatch.setattr(process_viewing_reminders, "_try_giveout_salvage", salvage)
    monkeypatch.setattr(process_viewing_reminders, "_send_pre_cancel_number_ask", ask)
    monkeypatch.setattr(process_viewing_reminders, "random_sleep", noop_async)
    monkeypatch.setattr(
        process_viewing_reminders,
        "release_conversation_claim",
        lambda thread_id, owner: released.append((thread_id, owner)),
    )

    asyncio.run(
        process_viewing_reminders.process_account_viewing_reminders(
            account, object(), worker_id="worker-1"
        )
    )

    assert cancel_calls == []
    assert salvage_calls == []
    assert ask_calls == []
    assert released == [("thread-waiting", "worker-1")]
