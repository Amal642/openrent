import re
from datetime import datetime, timedelta

from app.db.status import (
    VIEWING_DISCUSSION,
    VIEWING_BOOKED
)


def detect_stage(messages):

    combined = "\n".join(
        [
            m["message"].lower()
            for m in messages
        ]
    )

    # ---------------- BOOKED ----------------

    booked_patterns = [

        r"\bsee you\b",

        r"\bconfirmed\b",

        r"\bbooked\b",

        r"\bappointment\b",

        r"\bcome at\b",

        r"\bmeet at\b",

        r"\bsee you then\b",

        r"\bsee you tomorrow\b",
    ]

    for pattern in booked_patterns:

        if re.search(pattern, combined):

            return VIEWING_BOOKED

    # ---------------- DISCUSSION ----------------

    discussion_patterns = [

        r"\bwhat time\b",

        r"\bavailable\b",

        r"\bviewing\b",

        r"\bwhen can you\b",

        r"\bwhat day\b",
    ]

    for pattern in discussion_patterns:

        if re.search(pattern, combined):

            return VIEWING_DISCUSSION

    return None


def extract_viewing_datetime(messages, now=None):
    now = now or datetime.utcnow()
    combined = "\n".join(m["message"].lower() for m in messages)

    time_match = re.search(r"\b([01]?\d|2[0-3])(?::([0-5]\d))?\s*(am|pm)?\b", combined)
    if not time_match:
        return None

    hour = int(time_match.group(1))
    minute = int(time_match.group(2) or 0)
    suffix = time_match.group(3)

    if suffix == "pm" and hour < 12:
        hour += 12
    elif suffix == "am" and hour == 12:
        hour = 0

    target_date = now.date()

    if "day after tomorrow" in combined:
        target_date = (now + timedelta(days=2)).date()
    elif "tomorrow" in combined:
        target_date = (now + timedelta(days=1)).date()
    elif "today" in combined:
        target_date = now.date()
    else:
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
            if name in combined:
                days_ahead = (index - now.weekday()) % 7
                if days_ahead == 0:
                    days_ahead = 7
                target_date = (now + timedelta(days=days_ahead)).date()
                break

    candidate = datetime.combine(target_date, datetime.min.time()).replace(
        hour=hour,
        minute=minute,
    )

    if candidate < now:
        candidate += timedelta(days=1)

    return candidate
