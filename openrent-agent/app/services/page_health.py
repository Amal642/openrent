"""OpenRent page-health signals and fleet circuit breakers.

Every OpenRent step that depends on the page looking a certain way (login,
inbox, thread read, enquiry form, reply send, booking cancel, search results)
records one StepHealthEvent per attempt: ok=True when the page matched what the
code expects, ok=False when it did not. A single failure means little (one odd
listing, one slow proxy); the same step failing across several accounts in the
same hour means OpenRent changed the page. The alert bot's page-health check
(app/alerts/health_checks.py) reads these rows, raises a Telegram alert, and
trips a breaker that pauses the affected action fleet-wide until the step
works again.

Breakers live in app_settings ("breaker:<scope>") so every process sees them:
the rq workers that send, the backend scheduler and the alert bot.

Nothing here may raise into the caller: health bookkeeping must never break
the real operation.
"""
from __future__ import annotations

import contextvars
import json
from datetime import datetime, timedelta

from app.utils.logger import logger

# Steps. Keep names short and stable: they are stored and shown in alerts.
LOGIN = "login"
AUTH_MARKER = "auth_marker"
DISCOVERY = "discovery"
INBOX = "inbox"
THREAD_READ = "thread_read"
ENQUIRY_FORM = "enquiry_form"
ENQUIRY_SUBMIT = "enquiry_submit"
REPLY_SEND = "reply_send"
REPLY_SEEN = "reply_seen"
BOOKING_CANCEL = "booking_cancel"

STEP_LABELS = {
    LOGIN: "login",
    AUTH_MARKER: "logged-in page check",
    DISCOVERY: "search results",
    INBOX: "inbox list",
    THREAD_READ: "reading message threads",
    ENQUIRY_FORM: "enquiry form",
    ENQUIRY_SUBMIT: "enquiry submit confirmation",
    REPLY_SEND: "reply send (text left in the box)",
    REPLY_SEEN: "sent reply visible in thread",
    BOOKING_CANCEL: "Cancel Viewing form",
}

# Breaker scopes and the steps that trip them. Only steps whose failure means
# we may act wrongly (or keep hammering a broken form) pause anything; the
# rest already fail safe and only alert.
OUTREACH = "outreach"
REPLIES = "replies"
BREAKER_SCOPES = {
    ENQUIRY_FORM: OUTREACH,
    ENQUIRY_SUBMIT: OUTREACH,
    REPLY_SEND: REPLIES,
}

_current_account_id: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "page_health_account_id", default=None
)


def set_current_account(account_id: int | None) -> None:
    """Tag every step recorded in this asyncio task with the account. Called
    once at the top of the account worker; tasks inherit the context."""
    _current_account_id.set(account_id)


def record_step(step: str, ok: bool, detail: str | None = None, account_id: int | None = None) -> None:
    from app.db.models import StepHealthEvent
    from app.db.repository import session_scope

    if account_id is None:
        account_id = _current_account_id.get()
    try:
        with session_scope() as db:
            db.add(
                StepHealthEvent(
                    step=step,
                    account_id=account_id,
                    ok=bool(ok),
                    detail=(detail or "")[:300] or None,
                    created_at=datetime.utcnow(),
                )
            )
            db.commit()
    except Exception as exc:
        logger.warning(f"PAGE_HEALTH_RECORD_FAILED step={step} error={exc}")
    if not ok:
        logger.warning(f"PAGE_STEP_FAILED step={step} account_id={account_id} detail={detail!r}")


def _breaker_key(scope: str) -> str:
    return f"breaker:{scope}"


def breaker_state(scope: str) -> dict | None:
    """The active breaker for scope ({"until", "reason", "tripped_at"}), or
    None when the scope is running normally (never tripped or expired)."""
    from app.db.repository import get_app_setting

    try:
        raw = get_app_setting(_breaker_key(scope))
        if not raw:
            return None
        data = json.loads(raw)
        until = datetime.fromisoformat(data["until"])
    except Exception as exc:
        logger.warning(f"BREAKER_READ_FAILED scope={scope} error={exc}")
        return None
    if until <= datetime.utcnow():
        return None
    return data


def is_paused(scope: str) -> bool:
    return breaker_state(scope) is not None


def trip_breaker(scope: str, minutes: int, reason: str) -> None:
    from app.db.repository import set_app_setting

    now = datetime.utcnow()
    data = {
        "until": (now + timedelta(minutes=minutes)).isoformat(),
        "tripped_at": now.isoformat(),
        "reason": reason[:300],
    }
    try:
        set_app_setting(_breaker_key(scope), json.dumps(data))
        logger.warning(f"BREAKER_TRIPPED scope={scope} minutes={minutes} reason={reason!r}")
    except Exception as exc:
        logger.warning(f"BREAKER_TRIP_FAILED scope={scope} error={exc}")


def clear_breaker(scope: str, manual: bool = False) -> bool:
    """Lift a breaker early. Returns True if one was active.

    A manual lift (someone fixed the page code and sent /resume) also stamps
    the time, so the health check ignores the failures recorded before it and
    does not re-pause on stale evidence."""
    from app.db.repository import set_app_setting

    was_active = is_paused(scope)
    try:
        set_app_setting(_breaker_key(scope), "")
        if manual:
            set_app_setting(f"breaker_resumed:{scope}", datetime.utcnow().isoformat())
    except Exception as exc:
        logger.warning(f"BREAKER_CLEAR_FAILED scope={scope} error={exc}")
        return False
    if was_active or manual:
        logger.info(f"BREAKER_CLEARED scope={scope} manual={manual}")
    return was_active


def resumed_at(scope: str) -> datetime | None:
    """When this scope was last resumed by hand, if ever."""
    from app.db.repository import get_app_setting

    try:
        raw = get_app_setting(f"breaker_resumed:{scope}")
        return datetime.fromisoformat(raw) if raw else None
    except Exception:
        return None
