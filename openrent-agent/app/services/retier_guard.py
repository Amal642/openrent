"""Guard against changing an account's persona while it has live conversations.

Re-tiering (changing persona_type / name / job) is only safe on a *fresh*
account with no live threads. If an account has already sent an opening message
to a landlord stating one identity ("I'm an HR Business Partner..."), changing
the persona makes every subsequent reply describe a different person
("I work as a structural engineer...") — a blatant, bot-looking contradiction
in the same thread. This happened to accounts 29 & 31 on 2026-08-15.

A thread is "open" (contradiction risk) unless it is terminal
(HANDOFF_COMPLETE / VIEWING_CANCELLED / SHORT_TERM_PROPERTY) or explicitly
closed (CLOSED / REPLY_DISABLED — no further reply can be sent). Even a thread
that is only INITIAL_MESSAGE_SENT counts: if the landlord replies later, the
new persona answers and contradicts the opening.
"""
from __future__ import annotations

TERMINAL_STAGES = {"HANDOFF_COMPLETE", "VIEWING_CANCELLED", "SHORT_TERM_PROPERTY"}
CLOSED_STATUSES = {"CLOSED", "REPLY_DISABLED"}


class RetierBlocked(Exception):
    """Raised when re-tiering an account would contradict live conversations."""


def is_open_thread(status, stage) -> bool:
    """True if a reply on this thread could still be sent (contradiction risk)."""
    return stage not in TERMINAL_STAGES and status not in CLOSED_STATUSES


def count_open_threads(account_id: int, db=None) -> int:
    """Number of non-terminal, still-repliable threads owned by the account."""
    from app.db.connection import SessionLocal
    from app.db.models import Conversation, Listing, SearchProfile

    own = db is None
    db = db or SessionLocal()
    try:
        rows = (
            db.query(Conversation.status, Conversation.conversation_stage)
            .join(Listing, Conversation.listing_id == Listing.id)
            .join(SearchProfile, Listing.search_profile_id == SearchProfile.id)
            .filter(SearchProfile.account_id == account_id)
            .all()
        )
        return sum(1 for status, stage in rows if is_open_thread(status, stage))
    finally:
        if own:
            db.close()


def assert_safe_to_retier(account_id: int, db=None) -> None:
    """Raise RetierBlocked if the account has any open thread."""
    n = count_open_threads(account_id, db)
    if n:
        raise RetierBlocked(
            f"Account {account_id} has {n} open (non-terminal) thread(s). "
            f"Re-tiering would contradict live landlord conversations "
            f"(the opening stated a different persona). Close/terminalize those "
            f"threads first, or call with force=True if you accept the contradiction."
        )


def retier_account(account_id: int, new_persona_type: str, *, force: bool = False) -> None:
    """Safely change an account's persona_type, then re-materialise the persona.

    Refuses (RetierBlocked) if the account has open threads unless force=True.
    Naming/job selection is left to ensure_account_persona; callers that need
    guaranteed-unique names should set them explicitly afterwards.
    """
    from app.db.connection import SessionLocal
    from app.db.models import Account
    from app.db.repository import ensure_account_persona

    if not force:
        assert_safe_to_retier(account_id)

    with SessionLocal() as db:
        acc = db.query(Account).get(account_id)
        if acc is None:
            raise ValueError(f"account {account_id} not found")
        acc.persona_type = new_persona_type
        for field in ("persona_name", "persona_partner_name", "persona_job",
                      "persona_partner_job", "conversation_style", "message_strategy",
                      "escalation_behavior", "conversation_goal", "phone_fetching_type",
                      "home_city"):
            if hasattr(acc, field):
                setattr(acc, field, None)
        db.commit()
    ensure_account_persona(account_id)
