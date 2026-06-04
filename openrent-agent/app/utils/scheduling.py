from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo


UK_TZ = ZoneInfo("Europe/London")

# Initial outreach window (sending first messages to landlords)
OUTREACH_START = time(8, 0)
OUTREACH_END = time(21, 0)

# Full system operating window — scheduler only queues jobs inside this range
OPERATING_START = time(8, 15)
OPERATING_END = time(22, 0)


def uk_now() -> datetime:
    return datetime.now(UK_TZ)


def is_uk_outreach_window(now: datetime | None = None) -> bool:
    """True when it is appropriate to send initial landlord enquiries."""
    current = now.astimezone(UK_TZ) if now else uk_now()
    if current.weekday() == 6:
        return False
    return OUTREACH_START <= current.time() <= OUTREACH_END


def is_operating_hours(now: datetime | None = None) -> bool:
    """
    True when the scheduler may queue any account work
    (scraping, outreach, replies, phone requests, viewing handling).

    Window: 08:15 – 22:00 Europe/London, every day.
    Outside this window the scheduler logs a sleep message and skips the tick.
    """
    current = now.astimezone(UK_TZ) if now else uk_now()
    return OPERATING_START <= current.time() <= OPERATING_END
