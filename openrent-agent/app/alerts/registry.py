"""
Subscriber registry for the Telegram alert bot: who is authorized to receive
alerts, plus the password-attempt rate limiter. Mirrors the shape of
app.api.auth's CRM login limiter (MAX_FAILED_LOGINS + time-windowed lockout)
but keyed by chat_id and persisted in the DB, since this is a long-running
process where an in-memory limiter would reset on every restart.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from werkzeug.security import check_password_hash

from app.config import settings
from app.db.models import AlertSubscriber
from app.db.repository import session_scope


def get_or_create_pending(
    chat_id: str, username: str | None = None, first_name: str | None = None
) -> AlertSubscriber:
    with session_scope() as db:
        row = db.query(AlertSubscriber).filter(AlertSubscriber.chat_id == chat_id).first()
        if row:
            if username and row.username != username:
                row.username = username
            if first_name and row.first_name != first_name:
                row.first_name = first_name
            db.commit()
            return row

        row = AlertSubscriber(
            chat_id=chat_id,
            username=username,
            first_name=first_name,
            joined_at=datetime.utcnow(),
        )
        db.add(row)
        db.commit()
        return row


def get_subscriber(chat_id: str) -> AlertSubscriber | None:
    with session_scope() as db:
        return db.query(AlertSubscriber).filter(AlertSubscriber.chat_id == chat_id).first()


def is_locked_out(chat_id: str) -> tuple[bool, int]:
    """Returns (locked, retry_after_seconds)."""
    with session_scope() as db:
        row = db.query(AlertSubscriber).filter(AlertSubscriber.chat_id == chat_id).first()
        if not row or not row.locked_until:
            return False, 0
        now = datetime.utcnow()
        if row.locked_until <= now:
            return False, 0
        return True, int((row.locked_until - now).total_seconds())


def record_failed_attempt(chat_id: str) -> tuple[int, bool]:
    """Returns (attempts_so_far, now_locked)."""
    with session_scope() as db:
        row = db.query(AlertSubscriber).filter(AlertSubscriber.chat_id == chat_id).first()
        if not row:
            return 0, False
        row.failed_attempts = (row.failed_attempts or 0) + 1
        locked = row.failed_attempts >= settings.ALERT_MAX_PASSWORD_ATTEMPTS
        if locked:
            row.locked_until = datetime.utcnow() + timedelta(seconds=settings.ALERT_LOCKOUT_SECONDS)
        row.updated_at = datetime.utcnow()
        db.commit()
        return row.failed_attempts, locked


def check_password(password: str) -> bool:
    if not settings.TELEGRAM_ALERT_PASSWORD_HASH:
        return False
    return check_password_hash(settings.TELEGRAM_ALERT_PASSWORD_HASH, password)


def authorize(chat_id: str) -> None:
    with session_scope() as db:
        row = db.query(AlertSubscriber).filter(AlertSubscriber.chat_id == chat_id).first()
        if not row:
            return
        row.authorized = True
        row.active = True
        row.failed_attempts = 0
        row.locked_until = None
        row.authorized_at = datetime.utcnow()
        row.updated_at = datetime.utcnow()
        db.commit()


def unsubscribe(chat_id: str) -> None:
    with session_scope() as db:
        row = db.query(AlertSubscriber).filter(AlertSubscriber.chat_id == chat_id).first()
        if row:
            row.authorized = False
            row.updated_at = datetime.utcnow()
            db.commit()


def deactivate(chat_id: str) -> None:
    """Delivery kept failing (e.g. the user blocked the bot) — stop retrying."""
    with session_scope() as db:
        row = db.query(AlertSubscriber).filter(AlertSubscriber.chat_id == chat_id).first()
        if row:
            row.active = False
            row.updated_at = datetime.utcnow()
            db.commit()


def get_authorized_subscribers() -> list[AlertSubscriber]:
    with session_scope() as db:
        return (
            db.query(AlertSubscriber)
            .filter(AlertSubscriber.authorized == True, AlertSubscriber.active == True)
            .all()
        )


def count_authorized() -> int:
    with session_scope() as db:
        return (
            db.query(AlertSubscriber)
            .filter(AlertSubscriber.authorized == True, AlertSubscriber.active == True)
            .count()
        )
