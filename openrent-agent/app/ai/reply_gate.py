"""Pure, dependency-free decision helpers for the reply worker.

Deliberately imports nothing (no DB / browser / LLM), so the reply-stop logic is
unit-testable in isolation (tests/test_reply_gate.py). The worker in
scripts/process_replies.py imports these helpers and performs the side effects.
"""


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
