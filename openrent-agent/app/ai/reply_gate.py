"""Pure, dependency-free decision helpers for the reply worker.

Deliberately imports nothing (no DB / browser / LLM), so the reply-stop logic is
unit-testable in isolation (tests/test_reply_gate.py). The worker in
scripts/process_replies.py imports these helpers and performs the side effects.
"""


import re


def post_capture_decision(conversation):
    """Decide whether to stop replying because the landlord's number is captured.

    The objective is the landlord's phone number. Once we have it, continuing to
    send "natural" replies is the post-capture spiral that gets accounts reported
    ("you keep sending the same message", "are you a bot"). This gate stops that,
    while never stranding a viewing that still needs cancelling.

    Returns:
      None              -- no number yet; proceed with the normal reply.
      "terminal"        -- number captured and nothing left to do; the thread
                           should be marked handoff-complete and skipped from now on.
      "pending_cancel"  -- number captured but a booked viewing still needs
                           cancelling; skip this reply but keep the thread
                           non-terminal so the cancellation flow still fires later.
    """
    if conversation is None or not getattr(conversation, "extracted_phone", None):
        return None
    viewing_needs_cancel = (
        getattr(conversation, "viewing_confirmed", False)
        and not getattr(conversation, "viewing_cancelled", False)
        and not getattr(conversation, "handoff_completed_at", None)
    )
    return "pending_cancel" if viewing_needs_cancel else "terminal"


# Landlord-initiated live-call / remote-viewing gates that we cannot attend. A
# real tenant would join; the automated tenant cannot, so agreeing produces a
# no-show + fabricated-excuse loop that gets the account reported (thread
# 45936155). Kept as a curated keyword set (not an LLM call) so the decision
# stays pure and unit-testable.
_VIDEO_CALL_PATTERNS = (
    r"video\s*-?\s*call",
    r"video\s*chat",
    r"\bvideocall\b",
    r"\bzoom\b",
    r"google\s*meet",
    r"meet\.google",
    r"microsoft\s*teams",
    r"\bteams\s*(?:call|meeting|chat)",
    r"\bskype\b",
    r"\bfacetime\b",
    r"whats\s*app\s*video",
    r"screening\s*call",
    r"quick\s*call\s*(?:first|before)",
    r"call\s*(?:first|before)\b[^.]*\bviewing",
    r"(?:hop|jump|get)\s*on\s*a\s*(?:quick\s*)?call",
    r"have\s*a\s*(?:quick\s*)?(?:video\s*)?call\b",
    r"call\s*to\s*get\s*to\s*know",
    r"get\s*to\s*know\s*you\b[^.]*\bcall",
    r"remote\s*viewing",
    r"virtual\s*viewing",
    r"view\b[^.]*\bremotely",
    r"show\b[^.]*\bremotely",
)
_VIDEO_CALL_RE = re.compile("|".join(_VIDEO_CALL_PATTERNS), re.IGNORECASE)


def landlord_wants_video_call(messages) -> bool:
    """True if any landlord/inbound message requests a live video/screening call
    or a remote viewing that the automated tenant cannot attend.

    Pure text scan over the landlord's messages (sender/direction not one of our
    own). Scans the whole thread, not just the latest message, because the gate
    is usually set in the landlord's first reply and persists across later
    logistics messages.
    """
    for message in messages or []:
        if not isinstance(message, dict):
            continue
        sender = str(message.get("sender") or message.get("direction") or "").lower()
        if sender in {"us", "user", "tenant", "outbound", "ai", "assistant"}:
            continue  # our own message
        text = str(message.get("message") or message.get("content") or "")
        if text and _VIDEO_CALL_RE.search(text):
            return True
    return False
