import re
from datetime import datetime, timedelta, timezone

from app.db.status import (
    VIEWING_DISCUSSION,
    VIEWING_BOOKED,
    VIEWING_PENDING,
)


def _stage_log(event: str, detail: str = "") -> None:
    msg = f"STAGE_EVENT {event}"
    if detail:
        msg += f" | {detail}"
    print(msg)


BOOKED_PATTERNS = [
    r"\bsee you\b",
    r"\bconfirmed\b",
    r"\bbooked\b",
    r"\bappointment\b",
    r"\bcome at\b",
    r"\bmeet at\b",
    r"\bmeet you\b",
    r"\bsee you then\b",
    r"\bsee you tomorrow\b",
    r"\blooking forward to (meeting|seeing) you\b",
    r"\bsee you there\b",
]

DISCUSSION_PATTERNS = [
    r"\bwhat time\b",
    r"\bavailable\b",
    r"\bviewings?\b",
    r"\bwhen can you\b",
    r"\bwhat day\b",
    r"\brearrange\b",
    r"\breschedule\b",
    r"\banother time\b",
]

NEGATING_PATTERNS = [
    r"\bcancel\b",
    r"\bcan't make\b",
    r"\bcannot make\b",
    r"\bnot available\b",
    r"\bno longer\b",
]

TIME_PATTERN = re.compile(
    r"\b([01]?\d|2[0-3])(?:[:.]([0-5]\d))?\s*(am|pm)?\b",
    re.I,
)
WEEKDAY_PATTERN = re.compile(
    r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday|tomorrow|today)\b",
    re.I,
)
NUMERIC_DATE_PATTERN = re.compile(
    r"\b([0-3]?\d)[/-]([01]?\d)(?:[/-](\d{2,4}))?\b"
)
# Default hour for a viewing given only a part-of-day (no clock time), e.g.
# "Thursday evening" — used so such viewings still get a timed datetime (P3).
PART_OF_DAY_HOURS = {"morning": 10, "afternoon": 14, "evening": 18, "night": 19}


def _message_text(message):
    return str(message.get("message") or message.get("content") or "")


def _recent_messages(messages, limit=8):
    return list(messages or [])[-limit:]


def _matches_any(text, patterns):
    return any(re.search(pattern, text, re.I) for pattern in patterns)


def _date_spans(text):
    return [match.span() for match in NUMERIC_DATE_PATTERN.finditer(text)]


def _overlaps_any(span, spans):
    start, end = span
    return any(start < other_end and end > other_start for other_start, other_end in spans)


def _is_explicit_time_match(match) -> bool:
    """Return False for bare integers (e.g. '1' in '1 bed flat', '4' in '4 months').
    A real time reference requires either HH:MM format or an am/pm suffix."""
    has_minutes = match.group(2) is not None
    has_ampm = bool((match.group(3) or "").strip())
    return has_minutes or has_ampm


def _message_time(message):
    """Best-effort naive-UTC datetime for WHEN a message was sent.

    Relative/underspecified dates ("6:15pm", "Tuesday") must resolve against the
    moment the landlord spoke, not when the worker happens to process the thread
    (a processing lag pushed one real viewing 2 days into the future). Returns
    None when no timestamp is present, so callers fall back to `now`.
    """
    if not isinstance(message, dict):
        return None
    for key in ("timestamp", "received_at", "created_at"):
        value = message.get(key)
        if value in (None, ""):
            continue
        dt = value if isinstance(value, datetime) else _parse_message_ts(str(value))
        if dt is not None:
            if dt.tzinfo is not None:
                dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
            return dt
    return None


def _parse_message_ts(value):
    value = value.strip()
    if not value:
        return None
    try:
        if value.isdigit():
            numeric = int(value)
            if numeric > 10_000_000_000:  # milliseconds
                numeric = numeric / 1000
            return datetime.fromtimestamp(numeric, tz=timezone.utc)
    except Exception:
        pass
    for candidate in (value, value.replace("Z", "+00:00")):
        try:
            return datetime.fromisoformat(candidate)
        except Exception:
            pass
    return None


def _target_date_from_text(text, now):
    if "day after tomorrow" in text:
        return (now + timedelta(days=2)).date()
    if "tomorrow" in text:
        return (now + timedelta(days=1)).date()
    if "today" in text:
        return now.date()

    for match in NUMERIC_DATE_PATTERN.finditer(text):
        day = int(match.group(1))
        month = int(match.group(2))
        year_text = match.group(3)
        year = now.year
        if year_text:
            year = int(year_text)
            if year < 100:
                year += 2000
        try:
            candidate = datetime(year, month, day).date()
        except ValueError:
            continue
        if candidate < now.date() and not year_text:
            try:
                candidate = datetime(year + 1, month, day).date()
            except ValueError:
                continue
        return candidate

    weekdays = {
        "monday": 0,
        "tuesday": 1,
        "wednesday": 2,
        "thursday": 3,
        "friday": 4,
        "saturday": 5,
        "sunday": 6,
    }
    for name, index in weekdays.items():
        if name in text:
            days_ahead = (index - now.weekday()) % 7
            if days_ahead == 0:
                days_ahead = 7
            return (now + timedelta(days=days_ahead)).date()

    return now.date()


def _has_time(text):
    date_spans = _date_spans(text)
    return any(
        not _overlaps_any(match.span(), date_spans) and _is_explicit_time_match(match)
        for match in TIME_PATTERN.finditer(text)
    )


def _has_time_or_day(text):
    """True when text contains a numeric time OR a named weekday/day word.
    Used so 'See you Thursday' qualifies as VIEWING_BOOKED even without a
    specific clock time."""
    return _has_time(text) or bool(WEEKDAY_PATTERN.search(text))


def detect_stage(messages):
    recent = _recent_messages(messages, limit=8)
    if not recent:
        return None

    recent_text = "\n".join(_message_text(m).lower() for m in recent)
    latest_text = _message_text(recent[-1]).lower()

    if _matches_any(latest_text, NEGATING_PATTERNS):
        return VIEWING_DISCUSSION
    if _matches_any(
        latest_text,
        [
            r"\brearrange\b",
            r"\breschedule\b",
            r"\banother time\b",
            r"\binstead\b",
            r"\bneed to change\b",
            r"\bchange it\b",
        ],
    ):
        return VIEWING_DISCUSSION

    discussion_after_booking = False
    for message in recent[-4:]:
        text = _message_text(message).lower()
        if _matches_any(text, DISCUSSION_PATTERNS) and _matches_any(text, NEGATING_PATTERNS + [r"\bor\b", r"\binstead\b"]):
            discussion_after_booking = True
            break

    if discussion_after_booking:
        return VIEWING_DISCUSSION

    # VIEWING_BOOKED requires a booking phrase AND a specific time/day in the SAME
    # message. Combining signals across different messages causes false positives
    # (e.g. "that works" in one reply + "1 bed flat" in the opener).
    for message in recent:
        text = _message_text(message).lower()
        if _matches_any(text, BOOKED_PATTERNS) and _has_time_or_day(text):
            _stage_log("VIEWING_CONFIRMATION_DETECTED", "booked pattern + time/day in same message")
            return VIEWING_BOOKED

    # Booked-pattern found but no confirmed time — treat as pending, not booked
    if any(_matches_any(_message_text(m).lower(), BOOKED_PATTERNS) for m in recent):
        _stage_log("VIEWING_PENDING", "booked pattern found but no specific time agreed")
        return VIEWING_PENDING

    if _matches_any(recent_text, DISCUSSION_PATTERNS):
        _stage_log("VIEWING_PENDING", "viewing discussion detected, no confirmed time")
        return VIEWING_DISCUSSION

    return None


def _part_of_day_datetime(messages, now):
    """Fallback datetime for "Thursday evening"-style times with no clock time.

    Requires a day anchor (weekday/today/tomorrow) plus a part-of-day word, and
    maps the part-of-day to a default hour. Returns None if either is missing.
    """
    for message in reversed(list(messages or [])):
        text = _message_text(message).lower()
        if not WEEKDAY_PATTERN.search(text):
            continue
        ref = _message_time(message) or now
        for word, hour in PART_OF_DAY_HOURS.items():
            if word in text:
                target_date = _target_date_from_text(text, ref)
                candidate = datetime.combine(
                    target_date, datetime.min.time()
                ).replace(hour=hour)
                if candidate < ref:
                    candidate += timedelta(days=1)
                return candidate
    return None


def extract_viewing_datetime(messages, now=None):
    now = now or datetime.utcnow()
    recent = _recent_messages(messages, limit=8)

    candidates = []
    for message in recent:
        text = _message_text(message).lower()
        # Consider a message with an explicit time that is either about a viewing
        # OR references a specific day (today/tomorrow/weekday). The day clause
        # catches "6-6:30pm today" / "3pm I am here" that state a scheduled time
        # without a viewing keyword (P3), while still ignoring bare numbers like
        # "contact you in 1 day" (which carry no explicit time — see below).
        if not (
            TIME_PATTERN.search(text)
            and (
                _matches_any(text, BOOKED_PATTERNS + DISCUSSION_PATTERNS)
                or WEEKDAY_PATTERN.search(text)
            )
        ):
            continue
        # Anchor date resolution to WHEN this message was sent, not to the
        # worker's processing time. Falls back to `now` if the message carries
        # no timestamp (preserves prior behaviour and the explicit-now tests).
        ref = _message_time(message) or now
        for match in TIME_PATTERN.finditer(text):
            # Require an explicit time (:MM / .MM or am/pm). That alone excludes
            # bare date components like "05"/"06" in "05/06", so no date-overlap
            # check is needed — and dropping it lets "6-6:30pm" keep the 6:30pm
            # time that a greedy "6-6" numeric-date match would otherwise swallow.
            if not _is_explicit_time_match(match):
                continue
            candidates.append((text, match, ref))

    if not candidates:
        fallback = _part_of_day_datetime(recent, now)
        if fallback is not None:
            _stage_log("VIEWING_DATETIME_EXTRACTED", f"part-of-day default datetime={fallback}")
            return fallback
        _stage_log("VIEWING_DATETIME_EXTRACTED", "no candidates — no time found in booking/discussion messages")
        return None

    combined, time_match, ref = candidates[-1]

    if not time_match:
        return None

    hour = int(time_match.group(1))
    minute = int(time_match.group(2) or 0)
    suffix = (time_match.group(3) or "").lower()

    if suffix == "pm" and hour < 12:
        hour += 12
    elif suffix == "am" and hour == 12:
        hour = 0
    elif not suffix and 1 <= hour <= 7:
        hour += 12

    target_date = _target_date_from_text(combined, ref)

    candidate = datetime.combine(target_date, datetime.min.time()).replace(
        hour=hour,
        minute=minute,
    )

    if candidate < ref:
        candidate += timedelta(days=1)

    _stage_log("VIEWING_DATETIME_EXTRACTED", f"extracted datetime={candidate}")
    return candidate
