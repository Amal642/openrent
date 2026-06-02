from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo


UK_TZ = ZoneInfo("Europe/London")
OUTREACH_START = time(8, 0)
OUTREACH_END = time(21, 0)


def uk_now() -> datetime:
    return datetime.now(UK_TZ)


def is_uk_outreach_window(now: datetime | None = None) -> bool:
    current = now.astimezone(UK_TZ) if now else uk_now()
    if current.weekday() == 6:
        return False
    return OUTREACH_START <= current.time() <= OUTREACH_END
