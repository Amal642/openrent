import re
from datetime import datetime, timedelta

from app.ai.personas import LANDLORD_ATTITUDES, landlord_asked_for_phone, tenant_shared_phone


FRIENDLY_PATTERNS = [
    r"\bthanks\b",
    r"\bthank you\b",
    r"\bno problem\b",
    r"\bperfect\b",
    r"\bgreat\b",
    r"\blovely\b",
]

AGGRESSIVE_PATTERNS = [
    r"\bwaste(?:d|ing)? my time\b",
    r"\bserious only\b",
    r"\bstop\b",
    r"\bdon't\b.*\bmessage\b",
    r"\brude\b",
]

SUSPICIOUS_PATTERNS = [
    r"\bwho are you\b",
    r"\bprove\b",
    r"\bscam\b",
    r"\bwhy\b.*\bnumber\b",
    r"\bdetails first\b",
    r"\breferences\b",
]

HELPFUL_PATTERNS = [
    r"\bi can show\b",
    r"\bhappy to\b",
    r"\blet me know\b",
    r"\bavailable to show\b",
    r"\bcan arrange\b",
]

COLD_PATTERNS = [
    r"^(yes|no|ok|okay|fine|when\?|what time\?)$",
]


def _content(message):
    return str(message.get("message") or message.get("content") or "")


def _sender(message):
    return str(message.get("sender") or message.get("direction") or "").lower()


def landlord_messages(messages):
    return [
        message
        for message in messages or []
        if _sender(message) in {"landlord", "inbound"}
    ]


def outbound_count(messages):
    return len([
        message
        for message in messages or []
        if _sender(message) in {"user", "tenant", "outbound", "ai"}
    ])


def viewing_requested(messages):
    return bool(
        re.search(
            r"\b(viewing|view|come round|come over|appointment|see it|available)\b",
            "\n".join(_content(message).lower() for message in messages or []),
        )
    )


def latest_landlord_asked_for_phone(messages):
    landlords = landlord_messages(messages)
    if not landlords:
        return False
    return landlord_asked_for_phone(_content(landlords[-1]))


def detect_landlord_attitude(messages, previous=None):
    landlords = landlord_messages(messages)
    if not landlords:
        return previous if previous in LANDLORD_ATTITUDES else "responsive"

    latest = _content(landlords[-1]).strip().lower()
    recent_text = "\n".join(_content(message).lower() for message in landlords[-4:])

    if any(re.search(pattern, recent_text, re.I) for pattern in AGGRESSIVE_PATTERNS):
        return "aggressive"
    if any(re.search(pattern, recent_text, re.I) for pattern in SUSPICIOUS_PATTERNS):
        return "suspicious"
    if any(re.search(pattern, recent_text, re.I) for pattern in HELPFUL_PATTERNS):
        return "helpful"
    if any(re.search(pattern, recent_text, re.I) for pattern in FRIENDLY_PATTERNS):
        return "friendly"
    if any(re.search(pattern, latest, re.I) for pattern in COLD_PATTERNS):
        return "cold"

    latest_time = landlords[-1].get("created_at")
    previous_time = landlords[-2].get("created_at") if len(landlords) > 1 else None
    if isinstance(latest_time, datetime) and isinstance(previous_time, datetime):
        if latest_time - previous_time > timedelta(hours=24):
            return "slow_reply"

    return "responsive"


def phone_shared_state(messages, persona, conversation=None):
    if conversation and getattr(conversation, "phone_number_shared_at", None):
        return True
    return tenant_shared_phone(messages, (persona or {}).get("mobile_number"))
