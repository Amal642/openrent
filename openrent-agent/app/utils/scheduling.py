from __future__ import annotations

from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo


UK_TZ = ZoneInfo("Europe/London")

# Initial outreach window (sending first messages to landlords)
OUTREACH_START = time(8, 0)
OUTREACH_END = time(23, 0)

# Full system operating window — scheduler only queues jobs inside this range
OPERATING_START = time(8, 0)
OPERATING_END = time(23, 0)


def uk_now() -> datetime:
    return datetime.now(UK_TZ)


def is_uk_outreach_window(now: datetime | None = None) -> bool:
    """True for initial landlord enquiries from 08:00 until 23:00 UK time."""
    current = now.astimezone(UK_TZ) if now else uk_now()
    return OUTREACH_START <= current.time() < OUTREACH_END


def is_operating_hours(now: datetime | None = None) -> bool:
    """
    True when the scheduler may queue any account work
    (scraping, outreach, replies, phone requests, viewing handling).

    Window: 08:15 – 23:00 Europe/London, every day.
    Outside this window the scheduler logs a sleep message and skips the tick.
    """
    current = now.astimezone(UK_TZ) if now else uk_now()
    return OPERATING_START <= current.time() < OPERATING_END


def uk_naive_to_utc_naive(dt):
    """Interpret a naive datetime as a UK wall-clock time and return the naive
    UTC instant it denotes. DST (BST/GMT) is resolved by ZoneInfo from the date.

    Viewing times come from humans/banners in UK local time, but the whole
    cancellation system compares against datetime.utcnow(). Storing UK-local as
    if it were UTC produced a seasonal 1-hour skew (the cancel window fired late
    in summer). Canonicalise every stored viewing instant to naive UTC here.

    Passes None through. An already tz-aware value is just converted.
    """
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.replace(tzinfo=UK_TZ).astimezone(timezone.utc).replace(tzinfo=None)


def utc_naive_to_uk_naive(dt):
    """Inverse of uk_naive_to_utc_naive: naive UTC instant -> naive UK wall clock,
    for rendering a stored viewing time back to a UK-based human (dashboard)."""
    if dt is None:
        return None
    aware = dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
    return aware.astimezone(UK_TZ).replace(tzinfo=None)
