import re

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