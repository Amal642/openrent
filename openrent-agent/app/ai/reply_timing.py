"""Human-like reply pacing for the conversational reply path.

The worker sends a reply within ~10s of *scraping* a landlord message, and it
scrapes each thread on a ~48-minute sweep. Usually the sweep lag hides the
machine speed, but when a landlord messages just before a sweep they get a
reply seconds after they hit send — a bot tell (see thread 46230796, every turn
answered 8-19s after detection).

This module gates the conversational reply so it never goes out sooner than a
randomised, human-plausible delay after the landlord's REAL message time — the
OpenRent ``data-message-time`` already scraped into each message's ``timestamp``
(see ``extract_conversation``). There is no sleeping and no blocking: when the
delay has not yet elapsed the worker simply skips the thread this run, and the
next sweep re-checks it.

Because the delay is a deterministic function of ``(thread_id, latest landlord
message)`` it is identical on every sweep (so no state has to be persisted) and
reproducible in tests.

The gate is well-targeted: it only defers replies that would otherwise be
suspiciously fast. A message that arrived, say, 30 min before the sweep already
has ``elapsed > required`` and is sent immediately — so the normal ~half-cycle
reply latency is unchanged; only the too-fast cases move to the next sweep.
"""
import hashlib
from datetime import datetime

from app.ai.stages import _message_time, landlord_says_en_route


# Human reply-delay buckets: (weight, low_seconds, high_seconds). Skewed toward
# a few minutes with a long tail; a hard ~90s floor so nothing looks robotic.
_DELAY_BUCKETS = [
    (60, 90, 15 * 60),           # 60%: 1.5–15 min
    (30, 15 * 60, 60 * 60),      # 30%: 15–60 min
    (10, 60 * 60, 3 * 60 * 60),  # 10%: 1–3 h
]
_TOTAL_WEIGHT = sum(weight for weight, _, _ in _DELAY_BUCKETS)

# Sender labels that are NOT the landlord (in-memory messages use "us"; DB rows
# use "outbound"). Everything else is treated as an inbound landlord message.
_NON_LANDLORD_SENDERS = {"us", "user", "tenant", "outbound", "ai", "assistant"}


def _message_text(message):
    return str(message.get("message") or message.get("content") or "")


def _latest_landlord_message(messages):
    for message in reversed(list(messages or [])):
        if not isinstance(message, dict):
            continue
        sender = str(message.get("sender") or message.get("direction") or "").lower()
        if sender in _NON_LANDLORD_SENDERS:
            continue
        return message
    return None


def sample_human_delay_seconds(thread_id, anchor_text):
    """Deterministic, human-like reply delay in seconds for a (thread, message).

    A hash of the inputs is the RNG source, so the value is stable across every
    sweep (no persistence needed) and reproducible in tests.
    """
    digest = hashlib.sha256(f"{thread_id}|{anchor_text}".encode("utf-8")).digest()
    unit = int.from_bytes(digest[:8], "big") / float(1 << 64)  # [0, 1)
    pick = unit * _TOTAL_WEIGHT
    for weight, low, high in _DELAY_BUCKETS:
        if pick < weight:
            frac = pick / weight  # spread deterministically within the bucket
            return low + frac * (high - low)
        pick -= weight
    return float(_DELAY_BUCKETS[-1][2])


def reply_hold_remaining_seconds(messages, thread_id, now=None):
    """Seconds still to wait before a human-plausible reply may be sent.

    ``0`` means send now. Returns ``0`` (never hold) when:
      * the landlord is en route / the viewing is imminent — a fast reply is
        correct there; delaying coordination is worse than answering quickly; or
      * the latest landlord message carries no parseable real timestamp — we
        can't guarantee a floor, so don't block the reply.
    """
    now = now or datetime.utcnow()
    if landlord_says_en_route(messages):
        return 0.0
    latest = _latest_landlord_message(messages)
    if latest is None:
        return 0.0
    sent_at = _message_time(latest)  # naive UTC, or None
    if sent_at is None:
        return 0.0
    required = sample_human_delay_seconds(thread_id, _message_text(latest))
    elapsed = (now - sent_at).total_seconds()
    return max(0.0, required - elapsed)
