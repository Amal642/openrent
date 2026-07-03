"""
AlertManager: polls unprocessed alert_events, applies fire-once dedup against
alert_signatures, gets a cached AI explanation, formats, and broadcasts.

Takes a `broadcast` async callable rather than importing the telegram library
itself, so app.alerts.bot is the only module that knows about Telegram —
this stays easy to reason about and test on its own.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Awaitable, Callable

from app.alerts import explainer, formatter
from app.alerts.events import resolution_mode_for
from app.config import settings
from app.db.models import AlertEvent, AlertSignature
from app.db.repository import session_scope
from app.utils.logger import logger

BroadcastFn = Callable[[str], Awaitable[None]]


class AlertManager:
    def __init__(self, broadcast: BroadcastFn):
        self._broadcast = broadcast

    async def run_forever(self) -> None:
        logger.info(f"ALERT_MANAGER_STARTED poll_seconds={settings.ALERT_POLL_SECONDS}")
        while True:
            try:
                await self._process_pending()
            except Exception:
                logger.exception("ALERT_MANAGER_TICK_FAILED")
            await asyncio.sleep(settings.ALERT_POLL_SECONDS)

    async def _process_pending(self) -> None:
        for event in await asyncio.to_thread(self._fetch_pending):
            await self._handle_event(event)

    def _fetch_pending(self) -> list[AlertEvent]:
        with session_scope() as db:
            return (
                db.query(AlertEvent)
                .filter(AlertEvent.processed_at.is_(None))
                .order_by(AlertEvent.created_at.asc())
                .limit(50)
                .all()
            )

    async def _handle_event(self, event: AlertEvent) -> None:
        is_new, signature_row = await asyncio.to_thread(self._register_signature, event)

        if not is_new:
            await asyncio.to_thread(self._mark_processed, event.id, "deduped")
            return

        explanation = signature_row.ai_explanation
        if not explanation:
            explanation = await asyncio.to_thread(
                explainer.explain,
                source=event.source,
                title=event.title,
                detail=event.detail or "",
                context=event.context,
            )
            if explanation:
                await asyncio.to_thread(self._save_explanation, event.signature, explanation)

        text = formatter.format_alert(event, signature_row.resolution_mode, explanation)
        try:
            await self._broadcast(text)
            await asyncio.to_thread(self._mark_processed, event.id, "sent")
        except Exception:
            logger.exception(f"ALERT_BROADCAST_FAILED event_id={event.id}")
            await asyncio.to_thread(self._mark_processed, event.id, "error")

    def _register_signature(self, event: AlertEvent) -> tuple[bool, AlertSignature]:
        """Returns (is_new_incident, signature_row). Fire-once: an already-
        active signature is a duplicate; an inactive (resolved/recovered) one
        re-arms and counts as a new incident."""
        with session_scope() as db:
            row = (
                db.query(AlertSignature)
                .filter(AlertSignature.signature == event.signature)
                .first()
            )
            now = datetime.utcnow()

            if row and row.active:
                row.last_seen_at = now
                row.alert_count = (row.alert_count or 0) + 1
                db.commit()
                return False, row

            if row:
                row.active = True
                row.last_seen_at = now
                row.alert_count = (row.alert_count or 0) + 1
                row.resolved_at = None
                db.commit()
                return True, row

            row = AlertSignature(
                signature=event.signature,
                source=event.source,
                title=event.title,
                active=True,
                resolution_mode=resolution_mode_for(event.source),
                first_seen_at=now,
                last_seen_at=now,
                alert_count=1,
            )
            db.add(row)
            db.commit()
            return True, row

    def _save_explanation(self, signature: str, explanation: str) -> None:
        with session_scope() as db:
            row = db.query(AlertSignature).filter(AlertSignature.signature == signature).first()
            if row:
                row.ai_explanation = explanation
                db.commit()

    def _mark_processed(self, event_id: int, outcome: str) -> None:
        with session_scope() as db:
            row = db.query(AlertEvent).filter(AlertEvent.id == event_id).first()
            if row:
                row.processed_at = datetime.utcnow()
                row.outcome = outcome
                db.commit()

    def clear_signature_if_active(self, signature: str) -> bool:
        """Used by the health-check loop on recovery. Returns True if it
        actually cleared something (i.e. it really was alerting)."""
        with session_scope() as db:
            row = db.query(AlertSignature).filter(AlertSignature.signature == signature).first()
            if row and row.active:
                row.active = False
                row.resolved_at = datetime.utcnow()
                db.commit()
                return True
            return False

    # ---- Commands ----

    def resolve(self, keyword: str | None) -> list[str]:
        """Clears active manual-resolution signatures matching keyword (case-
        insensitive substring on source/title) and returns what was cleared.
        No keyword -> lists active manual incidents without clearing anything."""
        with session_scope() as db:
            rows = (
                db.query(AlertSignature)
                .filter(
                    AlertSignature.active == True,
                    AlertSignature.resolution_mode == "manual",
                )
                .all()
            )
            if not keyword:
                return [f"{r.source}: {r.title}" for r in rows]

            needle = keyword.lower()
            matched = [r for r in rows if needle in r.source.lower() or needle in r.title.lower()]
            cleared = []
            for row in matched:
                row.active = False
                row.resolved_at = datetime.utcnow()
                cleared.append(f"{row.source}: {row.title}")
            db.commit()
            return cleared

    def status_summary(self) -> dict:
        with session_scope() as db:
            active_incidents = (
                db.query(AlertSignature).filter(AlertSignature.active == True).all()
            )
            today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            events_today = (
                db.query(AlertEvent).filter(AlertEvent.created_at >= today_start).count()
            )
            return {
                "active_incidents": [f"{r.source}: {r.title}" for r in active_incidents],
                "events_today": events_today,
            }

    async def send_recovery_notice(self, source: str, title: str) -> None:
        try:
            await self._broadcast(formatter.format_recovery(source, title))
        except Exception:
            logger.exception(f"ALERT_RECOVERY_BROADCAST_FAILED source={source}")
