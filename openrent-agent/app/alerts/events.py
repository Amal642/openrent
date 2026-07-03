"""
Passive + active error ingestion for the Telegram alert pipeline.

report_error() is the single entry point every failure source calls (existing
except blocks, the health-check loop, or the alert_on_failure decorator for
new risky operations). It only ever writes a row to alert_events — it never
talks to Telegram directly, so a slow/broken Telegram API can't block a
scraper or the WhatsApp worker. app.alerts.manager.AlertManager polls
alert_events separately and does the actual dedup + explain + send.
"""
from __future__ import annotations

import asyncio
import functools
import json
from datetime import datetime
from typing import Any, Callable

from app.db.models import AlertEvent
from app.db.repository import session_scope
from app.utils.logger import logger

# Sources whose failures self-heal (health-checked on a timer) get cleared
# automatically on recovery. Everything else needs a human /resolve.
AUTO_CLEAR_SOURCES = {"proxy", "whatsapp"}


def resolution_mode_for(source: str) -> str:
    return "auto" if source in AUTO_CLEAR_SOURCES else "manual"


def make_signature(source: str, title: str, exception_type: str | None) -> str:
    return f"{source}:{title}:{exception_type or ''}"[:500]


def report_error(
    source: str,
    title: str,
    detail: str = "",
    *,
    severity: str = "error",
    context: dict[str, Any] | None = None,
    exc: BaseException | None = None,
) -> None:
    """Record one failure for the AlertManager to pick up. Safe to call from
    any process/thread — this only writes a row, never sends anything itself,
    and never raises (a broken alert path must not break the real operation)."""
    exception_type = type(exc).__name__ if exc is not None else None
    signature = make_signature(source, title, exception_type)
    try:
        with session_scope() as db:
            db.add(
                AlertEvent(
                    source=source,
                    title=title,
                    detail=detail or (str(exc) if exc else ""),
                    severity=severity,
                    context=json.dumps(context or {}, default=str),
                    exception_type=exception_type,
                    signature=signature,
                    created_at=datetime.utcnow(),
                )
            )
            db.commit()
    except Exception:
        logger.exception(f"ALERT_EVENT_WRITE_FAILED source={source} title={title!r}")


def alert_on_failure(source: str, title: str | None = None):
    """Decorator for new risky operations going forward (sync or async):
    reports the failure once via report_error() and re-raises, so existing
    error handling around the call site is unchanged. Existing except blocks
    should call report_error() directly instead — this decorator can't cleanly
    wrap a fragment of an existing try body."""

    def decorator(fn: Callable) -> Callable:
        if asyncio.iscoroutinefunction(fn):
            @functools.wraps(fn)
            async def async_wrapper(*args, **kwargs):
                try:
                    return await fn(*args, **kwargs)
                except Exception as exc:
                    report_error(source, title or fn.__name__, str(exc), exc=exc)
                    raise
            return async_wrapper

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except Exception as exc:
                report_error(source, title or fn.__name__, str(exc), exc=exc)
                raise
        return wrapper

    return decorator
