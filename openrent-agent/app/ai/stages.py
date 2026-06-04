import re
from datetime import datetime, timedelta

from app.db.status import (
    VIEWING_DISCUSSION,
    VIEWING_BOOKED
)


BOOKED_PATTERNS = [
    r"\bsee you\b",
    r"\bconfirmed\b",
    r"\bbooked\b",
    r"\bappointment\b",
    r"\bcome at\b",
    r"\bmeet at\b",
    r"\bsee you then\b",
    r"\bsee you tomorrow\b",
    r"\bthat works\b",
    r"\bworks for me\b",
]

DISCUSSION_PATTERNS = [
    r"\bwhat time\b",
    r"\bavailable\b",
    r"\bviewing\b",
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
    r"\b([01]?\d|2[0-3])(?::([0-5]\d))?\s*(am|pm)?\b",
    re.I,
)
NUMERIC_DATE_PATTERN = re.compile(
    r"\b([0-3]?\d)[/-]([01]?\d)(?:[/-](\d{2,4}))?\b"
)


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
        not _overlaps_any(match.span(), date_spans)
        for match in TIME_PATTERN.finditer(text)
    )


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

    booking_context = [
        message
        for message in recent
        if _matches_any(_message_text(message).lower(), BOOKED_PATTERNS)
        or _has_time(_message_text(message).lower())
    ]

    if booking_context:
        combined_booking = "\n".join(_message_text(m).lower() for m in booking_context[-4:])
        if _matches_any(combined_booking, BOOKED_PATTERNS) and _has_time(combined_booking):
            return VIEWING_BOOKED
        if _matches_any(latest_text, BOOKED_PATTERNS):
            return VIEWING_BOOKED

    if _matches_any(recent_text, DISCUSSION_PATTERNS):
        return VIEWING_DISCUSSION

    return None


def extract_viewing_datetime(messages, now=None):
    now = now or datetime.utcnow()
    recent = _recent_messages(messages, limit=8)

    candidates = []
    for index, message in enumerate(recent):
        text = _message_text(message).lower()
        if not (
            TIME_PATTERN.search(text)
            and (
                _matches_any(text, BOOKED_PATTERNS + DISCUSSION_PATTERNS)
                or index >= len(recent) - 3
            )
        ):
            continue
        date_spans = _date_spans(text)
        for match in TIME_PATTERN.finditer(text):
            if _overlaps_any(match.span(), date_spans):
                continue
            candidates.append((text, match))

    if not candidates:
        return None

    combined, time_match = candidates[-1]

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

    target_date = _target_date_from_text(combined, now)

    candidate = datetime.combine(target_date, datetime.min.time()).replace(
        hour=hour,
        minute=minute,
    )

    if candidate < now:
        candidate += timedelta(days=1)

    return candidate
