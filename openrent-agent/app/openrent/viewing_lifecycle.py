"""Shared viewing-withdrawal lifecycle helpers.

Extracted verbatim from scripts.process_replies (step 1 of consolidating
cancellation onto a single owner). These are the pre-withdrawal actions —
cancel, pre-cancel number-ask, and give-out salvage — that both the reply
loop and the DB-driven cancellation sweep need. Keeping them in one module
lets the sweep reuse the exact same behaviour instead of re-implementing it.

This step is a pure move: behaviour is unchanged and process_replies re-imports
these names, so every existing call site continues to work identically. Note
for tests: these functions resolve their dependencies (send_reply, can_reply,
get_automatic_cancellation_block_reason, ...) in THIS module's namespace, so
monkeypatch app.openrent.viewing_lifecycle.<name>, not process_replies.<name>.
"""
from datetime import datetime, timedelta

from app.ai.personas import generate_phone_share_reply
from app.ai.replies import (
    generate_cancel_viewing_message,
    generate_pre_cancel_number_ask,
)
from app.db.repository import (
    ensure_account_persona,
    get_automatic_cancellation_block_reason,
    get_conversation_by_thread_id,
    mark_handoff_complete,
    mark_our_number_shared,
    mark_phone_requested,
    mark_viewing_cancelled,
    save_message,
    update_conversation_status,
    update_last_processed_message,
)
from app.db.status import REPLY_DISABLED, VIEWING_CANCELLED
from app.openrent.inbox import can_reply, send_reply
from app.utils.logger import logger
from app.whatsapp.repository import record_handoff_intent


_DEFAULT_CANCEL_MSG = (
    "Thanks for arranging the viewing. Unfortunately something has come up and I won't be "
    "able to make it. Really sorry for the short notice."
)


async def _cancel_viewing_and_handoff(
    thread_id, messages, latest_landlord_message, page,
    persona=None, landlord_attitude=None,
):
    """Send a viewing cancellation, mark the viewing cancelled, and complete handoff."""
    block_reason = get_automatic_cancellation_block_reason(thread_id)
    if block_reason:
        logger.info(
            f"CANCELLATION_BLOCKED thread_id={thread_id} reason={block_reason}"
        )
        return False

    logger.info(f"VIEWING_CANCEL_TRIGGERED thread_id={thread_id}")

    cancel_msg, error = generate_cancel_viewing_message(messages)
    if not cancel_msg or error:
        logger.warning(
            f"Cancel message generation failed for thread {thread_id}: "
            f"{error or 'empty_cancel_message'} — using fallback"
        )
        cancel_msg = _DEFAULT_CANCEL_MSG

    sent = await send_reply(page, cancel_msg)
    if not sent:
        still_open = await can_reply(page)
        if not still_open:
            logger.warning(
                f"VIEWING_CANCEL_REPLY_DISABLED thread_id={thread_id} "
                "textarea disabled — marking reply_disabled"
            )
            update_conversation_status(thread_id, REPLY_DISABLED)
            # If we already have the lead's number this thread is done: the
            # reply box is gone so it can never be cancelled or replied to.
            # Terminalize so P2 does not re-attempt it every run (CON-2). Gated
            # on phone-captured to avoid permanently killing a thread on a
            # transient page failure where we still want the number.
            _dead_conv = get_conversation_by_thread_id(thread_id)
            if _dead_conv and _dead_conv.extracted_phone:
                mark_handoff_complete(thread_id)
                logger.info(
                    f"VIEWING_CANCEL_DEADTHREAD_TERMINALIZED thread_id={thread_id}"
                )
        else:
            logger.warning(f"VIEWING_CANCEL_SEND_FAILED thread_id={thread_id}")
        return False

    logger.info(f"VIEWING_CANCEL_SENT thread_id={thread_id}")
    save_message(thread_id, "outbound", cancel_msg)
    update_last_processed_message(thread_id, latest_landlord_message)
    mark_viewing_cancelled(thread_id)
    mark_handoff_complete(thread_id)
    update_conversation_status(thread_id, VIEWING_CANCELLED)
    logger.info(f"HANDOFF_AFTER_CANCELLATION thread_id={thread_id}")
    return True


async def _send_pre_cancel_number_ask(
    thread_id, messages, latest_landlord_message, page,
    travel_city=None,
) -> bool:
    """Send a natural phone-ask message one run before cancelling a viewing."""
    msg, err = generate_pre_cancel_number_ask(messages, place=travel_city)
    if not msg or err:
        logger.warning(f"PRE_CANCEL_NUMBER_ASK_GEN_FAILED thread_id={thread_id} error={err}")
        return False
    sent = await send_reply(page, msg)
    if not sent:
        still_open = await can_reply(page)
        if not still_open:
            update_conversation_status(thread_id, REPLY_DISABLED)
        logger.warning(f"PRE_CANCEL_NUMBER_ASK_SEND_FAILED thread_id={thread_id}")
        return False
    save_message(thread_id, "outbound", msg)
    update_last_processed_message(thread_id, latest_landlord_message)
    mark_phone_requested(thread_id)
    logger.info(f"PRE_CANCEL_NUMBER_ASK_SENT thread_id={thread_id}")
    return True


async def _try_giveout_salvage(
    thread_id, conversation, account, messages, latest_landlord_message, page,
    require_landlord_asked: bool = True,
) -> bool:
    """Share our WhatsApp give-out number before abandoning a no-phone viewing.

    A landlord who is willing to hand over their number but is blocked by
    OpenRent's in-platform redaction ("(Number Removed)") otherwise ends as a
    silent cancellation — a lost lead. Instead, hand them our give-out WhatsApp
    once so they still have a channel to reach us (and record a handoff intent
    so any later WhatsApp maps back to this property).

    Returns True when the give-out was sent so the caller can defer the cancel
    one run. Guarded on ``our_number_shared_at`` so it fires at most once; the
    next run then cancels normally if no lead arrived. ``require_landlord_asked``
    is True in the pre-cancel path (only salvage when the landlord engaged on
    contact details) and False in the post-cancel path (they already replied).
    """
    if getattr(conversation, "extracted_phone", None):
        return False
    if getattr(conversation, "our_number_shared_at", None):
        return False
    if require_landlord_asked and not getattr(conversation, "landlord_asked_phone_at", None):
        return False
    # Never salvage a long-dead viewing: the box is closed, so the send just
    # fails every run (this was the source of the 115 GIVEOUT_SALVAGE_SEND_FAILED
    # on stale threads). Aged-out threads are also skipped upstream now.
    _vd = getattr(conversation, "viewing_datetime", None)
    if _vd and _vd < datetime.utcnow() - timedelta(hours=48):
        return False
    persona = ensure_account_persona(account.id)
    mobile = (persona or {}).get("mobile_number")
    if not mobile:
        return False
    reply = generate_phone_share_reply(
        persona,
        landlord_attitude=getattr(conversation, "landlord_attitude", "responsive") or "responsive",
    )
    if not reply:
        return False
    sent = await send_reply(page, reply)
    if not sent:
        still_open = await can_reply(page)
        if not still_open:
            update_conversation_status(thread_id, REPLY_DISABLED)
        logger.warning(f"GIVEOUT_SALVAGE_SEND_FAILED thread_id={thread_id}")
        return False
    save_message(thread_id, "outbound", reply)
    mark_our_number_shared(thread_id)
    try:
        record_handoff_intent(thread_id)
    except Exception as exc:
        logger.warning(
            f"GIVEOUT_SALVAGE_HANDOFF_INTENT_SKIPPED thread_id={thread_id} error={exc}"
        )
    update_last_processed_message(thread_id, latest_landlord_message)
    logger.info(f"GIVEOUT_SALVAGE_SENT thread_id={thread_id}")
    return True
