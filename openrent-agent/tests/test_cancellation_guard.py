import asyncio
from types import SimpleNamespace

from scripts import process_replies, process_viewing_reminders


def test_reply_time_cancellation_is_blocked_while_phone_request_unanswered(
    monkeypatch,
):
    sent = []

    monkeypatch.setattr(
        process_replies,
        "get_automatic_cancellation_block_reason",
        lambda _thread_id: "awaiting_phone_request_response",
    )

    async def send_reply(_page, message):
        sent.append(message)
        return True

    monkeypatch.setattr(process_replies, "send_reply", send_reply)

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
    account = SimpleNamespace(id=1, email="tenant@example.test")
    sent = []
    released = []

    monkeypatch.setattr(
        process_viewing_reminders,
        "get_due_viewing_cancellations",
        lambda account_id: [
            {
                "thread_id": "thread-waiting",
                "viewing_datetime": object(),
                "viewing_confirmed": True,
                "conversation_stage": "VIEWING_BOOKED",
            }
        ],
    )
    monkeypatch.setattr(
        process_viewing_reminders,
        "claim_conversation",
        lambda *_args: True,
    )

    async def noop_async(*_args, **_kwargs):
        return None

    async def extract_conversation(_page):
        return []

    async def send_reply(_page, message):
        sent.append(message)
        return True

    monkeypatch.setattr(process_viewing_reminders, "open_thread", noop_async)
    monkeypatch.setattr(
        process_viewing_reminders,
        "extract_conversation",
        extract_conversation,
    )
    monkeypatch.setattr(
        process_viewing_reminders,
        "get_automatic_cancellation_block_reason",
        lambda _thread_id: "awaiting_phone_request_response",
    )
    monkeypatch.setattr(process_viewing_reminders, "send_reply", send_reply)
    monkeypatch.setattr(
        process_viewing_reminders,
        "release_conversation_claim",
        lambda thread_id, owner: released.append((thread_id, owner)),
    )

    asyncio.run(
        process_viewing_reminders.process_account_viewing_reminders(
            account,
            object(),
            worker_id="worker-1",
        )
    )

    assert sent == []
    assert released == [("thread-waiting", "worker-1")]
