"""
Kapso WhatsApp transport.

This replaces the old Playwright WhatsApp Web automation while preserving the
existing message matching, reply scheduling, and cancellation logic.
"""
from __future__ import annotations

import asyncio
import json
import re
from contextlib import suppress
from datetime import datetime, timedelta
from typing import Optional

import httpx

from app.config import settings
from app.utils.logger import logger
from app.utils.text import strip_ai_dashes
from app.whatsapp.lines import accepted_phone_number_ids, meta_send_phone_number_id

_DISPATCH_INTERVAL_SECONDS = 60

# WhatsApp only allows free-text messages within 24h of the landlord's last
# message (the customer-service window). Outside it Meta rejects the send, so
# retrying (with an AI call each time for cancellations) only burned calls:
# ~8.5k failed sends/day before 2026-09-29. Keep a small safety margin.
_SERVICE_WINDOW = timedelta(hours=23, minutes=45)
_SEND_RETRY_DELAY = timedelta(minutes=15)


def _provider() -> str:
    return "meta" if settings.WHATSAPP_PROVIDER == "meta" else "kapso"


def _missing_env() -> list[str]:
    if _provider() == "meta":
        required = {
            "META_WA_ACCESS_TOKEN": settings.META_WA_ACCESS_TOKEN,
            "META_WA_PHONE_NUMBER_ID": settings.META_WA_PHONE_NUMBER_ID,
        }
    else:
        required = {
            "KAPSO_API_KEY": settings.KAPSO_API_KEY,
            "KAPSO_PHONE_NUMBER_ID": settings.KAPSO_PHONE_NUMBER_ID,
        }
    return [name for name, value in required.items() if not value]


def _phone_number_id(line_phone_number_id: Optional[str] = None) -> str:
    if _provider() == "meta":
        return meta_send_phone_number_id(line_phone_number_id)
    # Kapso's API key is bound to its single project number.
    return settings.KAPSO_PHONE_NUMBER_ID


def _send_target(line_phone_number_id: Optional[str] = None) -> tuple[str, dict]:
    """(messages URL, auth headers) for the configured provider and line.

    Kapso proxies Meta's Graph API, so the payload is identical; only the base
    URL and the auth header change.
    """
    if _provider() == "meta":
        base = settings.META_GRAPH_BASE_URL
        headers = {"Authorization": f"Bearer {settings.META_WA_ACCESS_TOKEN}"}
    else:
        base = settings.KAPSO_BASE_URL
        headers = {"X-API-Key": settings.KAPSO_API_KEY}
    number_id = _phone_number_id(line_phone_number_id)
    return f"{base.rstrip('/')}/{number_id}/messages", headers


def _contact_line(phone: str) -> Optional[str]:
    """Line a contact last wrote to, for callers that only pass a phone."""
    from app.whatsapp.repository import get_contact_by_phone

    contact = get_contact_by_phone(phone)
    return getattr(contact, "line_phone_number_id", None) if contact else None


def service_window_open(contact, now: Optional[datetime] = None) -> bool:
    """True when a free-text WhatsApp message can still reach this contact."""
    last = getattr(contact, "last_received_at", None)
    if not last:
        return False
    return (now or datetime.utcnow()) - last < _SERVICE_WINDOW


class KapsoWhatsAppWorker:
    """Singleton transport worker for sending WhatsApp messages through Kapso."""

    def __init__(self):
        self._poll_task: Optional[asyncio.Task] = None
        self._send_lock = asyncio.Lock()
        self.status: str = "disconnected"
        self.last_active: Optional[datetime] = None
        self.last_error: Optional[str] = None
        self.error_count: int = 0
        # Contacts already logged as window-closed (log once, not every minute).
        self._window_closed_logged: set[int] = set()

    async def start(self) -> None:
        if self.status in ("connected", "starting"):
            logger.info(f"WHATSAPP_KAPSO_START_SKIPPED status={self.status}")
            return

        self.status = "starting"
        await self._publish_status()

        missing = _missing_env()
        if missing:
            self.status = "error"
            self.last_error = f"Missing required env vars: {', '.join(missing)}"
            self.error_count += 1
            await self._publish_status()
            logger.error(f"WHATSAPP_KAPSO_START_FAILED missing={missing}")
            return

        self.status = "connected"
        self.last_error = None
        self.last_active = datetime.utcnow()
        await self._publish_status()
        self._poll_task = asyncio.create_task(
            self._dispatch_loop(), name="wa-kapso-dispatch"
        )
        logger.info(f"WHATSAPP_KAPSO_WORKER_STARTED provider={_provider()}")

    async def stop(self) -> None:
        if self._poll_task:
            self._poll_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._poll_task
            self._poll_task = None
        self.status = "disconnected"
        await self._publish_status()
        logger.info("WHATSAPP_KAPSO_WORKER_STOPPED")

    async def force_reconnect(self) -> None:
        logger.info("WHATSAPP_KAPSO_FORCE_RECONNECT")
        await self.stop()
        await self.start()

    def set_proxy(self, proxy_id: Optional[int]) -> None:
        logger.info(
            f"WHATSAPP_KAPSO_PROXY_IGNORED proxy_id={proxy_id} "
            "reason=Kapso API transport does not use browser proxies"
        )

    async def send_message(
        self, phone: str, text: str, line_phone_number_id: Optional[str] = None
    ) -> bool:
        if self.status != "connected":
            logger.warning(
                f"WHATSAPP_KAPSO_SEND_SKIPPED status={self.status} phone={phone}"
            )
            return False

        if line_phone_number_id is None and _provider() == "meta":
            try:
                line_phone_number_id = await asyncio.to_thread(_contact_line, phone)
            except Exception as exc:
                logger.warning(f"WHATSAPP_LINE_LOOKUP_FAILED phone={phone} error={exc}")

        async with self._send_lock:
            return await self._do_send(phone, text, line_phone_number_id)

    async def _do_send(
        self, phone: str, text: str, line_phone_number_id: Optional[str] = None
    ) -> bool:
        clean_phone = re.sub(r"\D", "", phone)
        if not clean_phone:
            logger.warning(f"WHATSAPP_KAPSO_SEND_FAILED phone={phone!r} reason=invalid_phone")
            return False

        # Single choke point for every WhatsApp outbound: em/en dashes are a bot tell.
        text = strip_ai_dashes(text)

        url, headers = _send_target(line_phone_number_id)
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": clean_phone,
            "type": "text",
            "text": {"body": text},
        }

        logger.info(
            f"WHATSAPP_KAPSO_SEND_START provider={_provider()} "
            f"line={_phone_number_id(line_phone_number_id)} "
            f"phone={clean_phone} text_len={len(text)}"
        )
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(url, headers=headers, json=payload)
            if response.status_code < 200 or response.status_code >= 300:
                self.last_error = response.text[:500]
                self.error_count += 1
                logger.error(
                    f"WHATSAPP_KAPSO_SEND_FAILED phone={clean_phone} "
                    f"status_code={response.status_code} body={response.text[:500]!r}"
                )
                return False
        except Exception as exc:
            self.last_error = str(exc)
            self.error_count += 1
            logger.error(f"WHATSAPP_KAPSO_SEND_ERROR phone={clean_phone} error={exc}")
            return False

        self.last_active = datetime.utcnow()
        await self._publish_status()
        logger.info(f"WHATSAPP_KAPSO_SENT phone={clean_phone}")
        return True

    async def _dispatch_loop(self) -> None:
        logger.info(
            f"WHATSAPP_KAPSO_DISPATCH_LOOP_STARTED interval={_DISPATCH_INTERVAL_SECONDS}s"
        )
        while True:
            try:
                await asyncio.sleep(_DISPATCH_INTERVAL_SECONDS)
                await self._publish_status()
                if self.status != "connected":
                    continue
                await self._dispatch_due_cancellations()
                await self._dispatch_due_replies()
            except asyncio.CancelledError:
                logger.info("WHATSAPP_KAPSO_DISPATCH_LOOP_CANCELLED")
                raise
            except Exception as exc:
                self.error_count += 1
                self.last_error = str(exc)
                await self._publish_status()
                logger.error(f"WHATSAPP_KAPSO_DISPATCH_ERROR error={exc}")

    async def _dispatch_due_cancellations(self) -> None:
        from app.ai.replies import generate_cancellation_message
        from app.db.repository import (
            get_automatic_cancellation_block_reason,
            mark_viewing_cancelled,
            save_message,
        )
        from app.whatsapp.repository import (
            append_outbound_message,
            get_contact_messages_for_ai,
            get_contacts_due_for_cancellation,
            get_conversation_for_contact,
            mark_contact_cancelled,
        )

        contacts = await asyncio.to_thread(get_contacts_due_for_cancellation)
        if not contacts:
            return

        logger.info(f"WHATSAPP_KAPSO_CANCELLATION_DUE count={len(contacts)}")
        for contact in contacts:
            # Check the window BEFORE generating the (AI) cancellation text.
            if not service_window_open(contact):
                if contact.id not in self._window_closed_logged:
                    self._window_closed_logged.add(contact.id)
                    logger.info(
                        f"WHATSAPP_KAPSO_CANCELLATION_WINDOW_CLOSED "
                        f"phone={contact.phone_number} contact_id={contact.id} "
                        f"last_received_at={contact.last_received_at}"
                    )
                continue

            conversation = await asyncio.to_thread(get_conversation_for_contact, contact)
            thread_id = conversation.thread_id if conversation else None

            if thread_id:
                block_reason = await asyncio.to_thread(
                    get_automatic_cancellation_block_reason, thread_id
                )
                if block_reason:
                    logger.info(
                        f"WHATSAPP_KAPSO_CANCELLATION_BLOCKED "
                        f"phone={contact.phone_number} reason={block_reason}"
                    )
                    continue

            history = await asyncio.to_thread(get_contact_messages_for_ai, contact)
            msg, error = await asyncio.to_thread(generate_cancellation_message, history)
            if not msg or error:
                logger.warning(
                    f"WHATSAPP_KAPSO_CANCELLATION_AI_FAILED "
                    f"phone={contact.phone_number} error={error}"
                )
                continue

            ok = await self.send_message(
                contact.phone_number,
                msg,
                line_phone_number_id=getattr(contact, "line_phone_number_id", None),
            )
            if ok:
                await asyncio.to_thread(append_outbound_message, contact.id, msg)
                await asyncio.to_thread(mark_contact_cancelled, contact.id)
                if thread_id:
                    await asyncio.to_thread(save_message, thread_id, "outbound", msg)
                    await asyncio.to_thread(mark_viewing_cancelled, thread_id)
                logger.info(
                    f"WHATSAPP_KAPSO_CANCELLATION_SENT "
                    f"phone={contact.phone_number} contact_id={contact.id}"
                )

    async def _dispatch_due_replies(self) -> None:
        from app.whatsapp.repository import (
            append_outbound_message,
            get_due_contacts,
            last_message_direction,
            mark_reply_sent,
            outbound_message_count,
            outbound_message_exists,
            update_contact,
        )
        from app.whatsapp.handler import MAX_AUTOMATED_REPLIES

        contacts = await asyncio.to_thread(get_due_contacts)
        if not contacts:
            return

        logger.info(f"WHATSAPP_KAPSO_DISPATCH due_count={len(contacts)}")
        for contact in contacts:
            # Scrub here too so the duplicate check and stored history match the sent text.
            reply = strip_ai_dashes(getattr(contact, "last_ai_reply", None))
            if not reply:
                await asyncio.to_thread(mark_reply_sent, contact.id)
                continue

            sent_count = await asyncio.to_thread(outbound_message_count, contact.id)
            if sent_count >= MAX_AUTOMATED_REPLIES:
                await asyncio.to_thread(
                    update_contact,
                    contact.id,
                    status="MAX_REPLIES_REACHED",
                    reply_scheduled_at=None,
                    last_ai_reply=None,
                )
                logger.info(
                    f"WHATSAPP_KAPSO_REPLY_SUPPRESSED_MAX_REPLIES "
                    f"phone={contact.phone_number} sent_count={sent_count} "
                    f"max={MAX_AUTOMATED_REPLIES}"
                )
                continue

            if await asyncio.to_thread(outbound_message_exists, contact.id, reply):
                await asyncio.to_thread(
                    update_contact,
                    contact.id,
                    status="MAX_REPLIES_REACHED",
                    reply_scheduled_at=None,
                    last_ai_reply=None,
                )
                logger.warning(
                    f"WHATSAPP_KAPSO_REPLY_SUPPRESSED_DUPLICATE_TEXT "
                    f"phone={contact.phone_number}"
                )
                continue

            if not service_window_open(contact):
                # Stale reply the landlord can no longer receive; drop it.
                await asyncio.to_thread(mark_reply_sent, contact.id)
                logger.info(
                    f"WHATSAPP_KAPSO_REPLY_DROPPED_WINDOW_CLOSED "
                    f"phone={contact.phone_number} last_received_at={contact.last_received_at}"
                )
                continue

            if await asyncio.to_thread(last_message_direction, contact) == "outbound":
                logger.info(
                    f"WHATSAPP_KAPSO_REPLY_SKIPPED_AWAITING_LANDLORD "
                    f"phone={contact.phone_number}"
                )
                await asyncio.to_thread(mark_reply_sent, contact.id)
                continue

            ok = await self.send_message(
                contact.phone_number,
                reply,
                line_phone_number_id=getattr(contact, "line_phone_number_id", None),
            )
            if ok:
                await asyncio.to_thread(append_outbound_message, contact.id, reply)
                await asyncio.to_thread(mark_reply_sent, contact.id)
                logger.info(
                    f"WHATSAPP_KAPSO_REPLY_DISPATCHED "
                    f"phone={contact.phone_number} status={contact.status}"
                )
            else:
                new_time = datetime.utcnow() + _SEND_RETRY_DELAY
                await asyncio.to_thread(
                    update_contact, contact.id, reply_scheduled_at=new_time
                )
                logger.warning(
                    f"WHATSAPP_KAPSO_REPLY_RESCHEDULED phone={contact.phone_number}"
                )

    async def _publish_status(self) -> None:
        try:
            from app.db.repository import set_app_setting

            await asyncio.to_thread(
                set_app_setting,
                "whatsapp_worker_heartbeat",
                json.dumps(
                    {
                        "status": self.status,
                        "transport": _provider(),
                        "at": datetime.utcnow().isoformat(),
                        "last_active": self.last_active.isoformat()
                        if self.last_active
                        else None,
                        "last_error": self.last_error,
                        "error_count": self.error_count,
                        "qr_available": False,
                    }
                ),
            )
        except Exception as exc:
            logger.warning(f"WHATSAPP_KAPSO_STATUS_PUBLISH_FAILED error={exc}")

    def get_status_dict(self) -> dict:
        return {
            "status": self.status,
            "transport": _provider(),
            "phone_number_id": _phone_number_id(),
            "lines": sorted(accepted_phone_number_ids()) if _provider() == "meta" else [],
            "last_active": self.last_active.isoformat() if self.last_active else None,
            "last_error": self.last_error,
            "error_count": self.error_count,
            "qr_available": False,
        }


_worker: Optional[KapsoWhatsAppWorker] = None


def get_worker() -> KapsoWhatsAppWorker:
    global _worker
    if _worker is None:
        _worker = KapsoWhatsAppWorker()
    return _worker


async def start_whatsapp_worker() -> None:
    worker = get_worker()
    asyncio.create_task(worker.start(), name="wa-kapso-start")
    logger.info("WHATSAPP_KAPSO_WORKER_QUEUED")


async def stop_whatsapp_worker() -> None:
    global _worker
    if _worker:
        await _worker.stop()
