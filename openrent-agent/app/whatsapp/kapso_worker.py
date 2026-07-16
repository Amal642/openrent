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

_DISPATCH_INTERVAL_SECONDS = 60


class KapsoWhatsAppWorker:
    """Singleton transport worker for sending WhatsApp messages through Kapso."""

    def __init__(self):
        self._poll_task: Optional[asyncio.Task] = None
        self._send_lock = asyncio.Lock()
        self.status: str = "disconnected"
        self.last_active: Optional[datetime] = None
        self.last_error: Optional[str] = None
        self.error_count: int = 0

    async def start(self) -> None:
        if self.status in ("connected", "starting"):
            logger.info(f"WHATSAPP_KAPSO_START_SKIPPED status={self.status}")
            return

        self.status = "starting"
        await self._publish_status()

        missing = []
        if not settings.KAPSO_API_KEY:
            missing.append("KAPSO_API_KEY")
        if not settings.KAPSO_PHONE_NUMBER_ID:
            missing.append("KAPSO_PHONE_NUMBER_ID")

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
        logger.info("WHATSAPP_KAPSO_WORKER_STARTED")

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

    async def send_message(self, phone: str, text: str) -> bool:
        if self.status != "connected":
            logger.warning(
                f"WHATSAPP_KAPSO_SEND_SKIPPED status={self.status} phone={phone}"
            )
            return False

        async with self._send_lock:
            return await self._do_send(phone, text)

    async def _do_send(self, phone: str, text: str) -> bool:
        clean_phone = re.sub(r"\D", "", phone)
        if not clean_phone:
            logger.warning(f"WHATSAPP_KAPSO_SEND_FAILED phone={phone!r} reason=invalid_phone")
            return False

        url = (
            f"{settings.KAPSO_BASE_URL.rstrip('/')}/"
            f"{settings.KAPSO_PHONE_NUMBER_ID}/messages"
        )
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": clean_phone,
            "type": "text",
            "text": {"body": text},
        }
        headers = {"X-API-Key": settings.KAPSO_API_KEY}

        logger.info(
            f"WHATSAPP_KAPSO_SEND_START phone={clean_phone} text_len={len(text)}"
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

            ok = await self.send_message(contact.phone_number, msg)
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
            reply = getattr(contact, "last_ai_reply", None)
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

            if await asyncio.to_thread(last_message_direction, contact) == "outbound":
                logger.info(
                    f"WHATSAPP_KAPSO_REPLY_SKIPPED_AWAITING_LANDLORD "
                    f"phone={contact.phone_number}"
                )
                await asyncio.to_thread(mark_reply_sent, contact.id)
                continue

            ok = await self.send_message(contact.phone_number, reply)
            if ok:
                await asyncio.to_thread(append_outbound_message, contact.id, reply)
                await asyncio.to_thread(mark_reply_sent, contact.id)
                logger.info(
                    f"WHATSAPP_KAPSO_REPLY_DISPATCHED "
                    f"phone={contact.phone_number} status={contact.status}"
                )
            else:
                new_time = datetime.utcnow() + timedelta(minutes=5)
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
                        "transport": "kapso",
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
            "transport": "kapso",
            "phone_number_id": settings.KAPSO_PHONE_NUMBER_ID,
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
