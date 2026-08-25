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


def unanswered_landlord_messages(messages):
    """The landlord messages since our last outbound reply — the burst we have
    not answered yet. This is the correct unit of "what is the landlord asking
    right now", because landlords often send several messages in a row (their
    number in one, a viewing time in the next). Reading only the final message
    misses the earlier ones (the Sandra/Claire lost-lead: "send me the number"
    followed by "can you come at 12?" — the ask sat in the non-final message).

    Falls back to the most recent landlord message when the last message is ours
    (nothing new since we replied), so behaviour is never worse than latest-only.
    """
    trailing = []
    for message in reversed(messages or []):
        if _sender(message) in {"landlord", "inbound"}:
            trailing.append(message)
        else:
            break
    trailing.reverse()
    if trailing:
        return trailing
    landlords = landlord_messages(messages)
    return [landlords[-1]] if landlords else []


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
    # Any message in the unanswered burst that asks for our number counts —
    # an ask we have not answered still stands even if a later message in the
    # same burst moved on to logistics.
    return any(
        landlord_asked_for_phone(_content(m))
        for m in unanswered_landlord_messages(messages)
    )


_HESITANT_PHONE_PATTERNS = [
    re.compile(
        r"\b(don'?t|do not|won'?t|would not|not comfortable|not happy|"
        r"prefer not to|rather not|wouldn'?t)\b.{0,60}"
        r"\b(give|share|provide|send|pass|hand).{0,30}\b(number|contact|phone|mobile)\b",
        re.I,
    ),
    re.compile(
        r"\b(prefer|happy|rather|want).{0,40}"
        r"\b(keep|stay|stick|communicate|message|talk).{0,30}"
        r"\b(here|on here|openrent|app|platform|this)\b",
        re.I,
    ),
    re.compile(
        r"\bkeep\b.{0,30}\b(on here|through here|via this|on openrent|on the app)\b",
        re.I,
    ),
    re.compile(
        r"\b(number|contact|phone)\b.{0,60}\b(once|when|after|until).{0,40}"
        r"\b(we meet|we'?ve met|you'?ve seen|we know|i know|viewi)\b",
        re.I,
    ),
    re.compile(
        r"\bnot.{0,20}\bshare.{0,30}\b(number|phone|mobile)\b.{0,40}"
        r"\b(haven'?t|not|don'?t).{0,20}\b(met|know)\b",
        re.I,
    ),
    re.compile(
        r"\blet'?s\b.{0,30}\b(keep|stick|stay).{0,30}\b(messages|messaging|this|here|app)\b",
        re.I,
    ),
]


def latest_landlord_hesitant_about_phone(messages):
    """True if any message in the unanswered landlord burst shows reluctance to
    share their number. A later message where they DO share is handled upstream
    via landlord_already_gave_number / phone extraction, so 'any in burst' is safe."""
    return any(
        any(p.search(_content(m)) for p in _HESITANT_PHONE_PATTERNS)
        for m in unanswered_landlord_messages(messages)
    )


# Each entry: (compiled regex, topic label)
_SCREENING_PATTERNS = [
    (re.compile(r"\byour (full\s+)?name\b", re.I), "name"),
    (re.compile(r"\bwhat('s| is) your name\b", re.I), "name"),
    (re.compile(r"\bname (please|and|,)\b", re.I), "name"),
    (re.compile(r"\bwhat (do you|does your (partner|wife|husband))? (do|work)\b", re.I), "employment"),
    (re.compile(r"\boccupation\b", re.I), "employment"),
    (re.compile(r"\bemployment\b", re.I), "employment"),
    (re.compile(r"\bjob (title|role|position)\b", re.I), "employment"),
    (re.compile(r"\b(move.?in|moving.?in|move.?date|start date|how soon|when (would|are|do) you)\b", re.I), "move_date"),
    (re.compile(r"\b(income|earn|salary|earnings|afford)\b", re.I), "income"),
    (re.compile(r"\breferences?\b", re.I), "references"),
    (re.compile(r"\bcredit (check|history|score)\b", re.I), "credit"),
    (re.compile(r"\bhow long\b", re.I), "tenancy_length"),
    (re.compile(r"\blength of tenancy\b", re.I), "tenancy_length"),
    (re.compile(r"\bpets?\b", re.I), "pets"),
    (re.compile(r"\b(current|previous|past) address\b", re.I), "address"),
    (re.compile(r"\b(answers? to|answer (the|my|our)|these) questions?\b", re.I), "questions"),
    (re.compile(r"\bscreening\b", re.I), "questions"),
]


def detect_screening_questions(messages) -> list[str]:
    """Return detected question topic names from the latest landlord message.

    An empty list means no screening questions were detected.  A non-empty list
    means the AI must answer these topics before any other objective.
    """
    # Aggregate topics across EVERY unanswered landlord message: all pending
    # screening questions must be answered, not just those in the final message.
    detected: list[str] = []
    seen: set[str] = set()
    for message in unanswered_landlord_messages(messages):
        text = _content(message)
        for pattern, topic in _SCREENING_PATTERNS:
            if topic not in seen and pattern.search(text):
                detected.append(topic)
                seen.add(topic)
    return detected


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
