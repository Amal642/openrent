import asyncio
from datetime import datetime

from app.browser.auth import login
from app.browser.launcher import launch_browser
from app.db.repository import (
    claim_conversation,
    get_active_accounts,
    get_automatic_cancellation_block_reason,
    get_conversation_by_thread_id,
    get_due_viewing_cancellations,
    get_travel_city,
    release_conversation_claim,
    update_account_worker_state,
    update_conversation_status,
    viewing_cancellation_due,
)
from app.db.init_db import init_db
from app.db.status import AI_FAILED
from app.openrent.inbox import extract_conversation, get_latest_landlord_message, open_thread
from app.openrent.viewing_lifecycle import (
    _cancel_viewing_and_handoff,
    _send_pre_cancel_number_ask,
    _try_giveout_salvage,
)
from app.utils.human import random_sleep
from app.utils.logger import logger


async def process_account_viewing_reminders(account, page, worker_id=None):
    """Phase-2 viewing-withdrawal sweep — the single owner of viewing cancellation.

    DB-driven and inbox-independent: it opens each due thread directly by
    thread_id, so it is unaffected by the reply-inbox "you:" filter that starves
    the reply loop. For every confirmed viewing that has entered its cancel
    window it runs the full withdrawal lifecycle — give-out salvage -> pre-cancel
    number-ask (2-step) -> cancellation — with an imminent-viewing override.
    All sends reuse the shared app.openrent.viewing_lifecycle helpers, so the
    behaviour is identical to what the reply loop used to do inline.
    """
    owner = worker_id or f"account-{account.id}"
    due_viewings = get_due_viewing_cancellations(account_id=account.id)

    if not due_viewings:
        logger.info(f"No due viewing cancellations for {account.email}")
        return

    logger.info(
        f"Found {len(due_viewings)} due viewing cancellations for {account.email}"
    )

    for viewing in due_viewings:
        thread_id = viewing["thread_id"]

        # Pre-flight guard: last-line defence over the DB query, which already
        # applies the canonical viewing_cancellation_due() predicate. Keyed on the
        # authoritative viewing-state fields only — NOT conversation_stage, whose
        # drift (viewing_confirmed=True while stage=VIEWING_DISCUSSION) was exactly
        # what silently blocked cancellations and caused no-shows.
        if not viewing.get("viewing_datetime") or not viewing.get("viewing_confirmed"):
            logger.warning(
                f"CANCELLATION_BLOCKED thread_id={thread_id} "
                f"reason=missing_confirmed_viewing "
                f"viewing_datetime={viewing.get('viewing_datetime')} "
                f"viewing_confirmed={viewing.get('viewing_confirmed')}"
            )
            continue

        try:
            if not claim_conversation(thread_id, owner):
                logger.info(f"Cancellation skipped for claimed thread {thread_id}")
                continue

            await open_thread(page, thread_id)
            messages = await extract_conversation(page)

            # Re-load fresh state: a Phase-1 reply may have flipped fields
            # (phone captured, cancelled, handoff) since the candidate query ran.
            conversation = get_conversation_by_thread_id(thread_id)
            if not viewing_cancellation_due(conversation):
                logger.info(
                    f"VIEWING_WITHDRAWAL_SKIP thread_id={thread_id} "
                    "reason=not_due_on_refresh"
                )
                continue

            latest_landlord_message = get_latest_landlord_message(messages)

            viewing_dt = conversation.viewing_datetime
            phone_captured = bool(conversation.extracted_phone)
            phone_requested = bool(conversation.phone_requested_at)
            phone_ask_age_h = (
                (datetime.utcnow() - conversation.phone_requested_at).total_seconds() / 3600
                if phone_requested and conversation.phone_requested_at
                else 0
            )
            hrs_until = (
                (viewing_dt - datetime.utcnow()).total_seconds() / 3600
                if viewing_dt else None
            )
            # Imminent: within ~2h of a still-future viewing — withdraw NOW even
            # without the 4h phone-ask courtesy age (the same-day short-notice
            # no-show, audit #4). A pending phone request still holds it via
            # block_reason below.
            viewing_imminent = hrs_until is not None and 0 < hrs_until <= 2

            block_reason = get_automatic_cancellation_block_reason(thread_id)

            safe_to_cancel = not block_reason and (
                viewing_imminent
                or phone_captured
                or (phone_requested and phone_ask_age_h >= 4)
            )

            if safe_to_cancel:
                # Salvage before withdrawing: hand over our WhatsApp give-out once
                # (a willing-but-redacted landlord can still reach us) and defer the
                # cancel one run. Guarded on our_number_shared_at so it fires once;
                # the next sweep run then cancels normally if no lead arrived.
                if await _try_giveout_salvage(
                    thread_id, conversation, account, messages,
                    latest_landlord_message, page,
                ):
                    logger.info(
                        f"VIEWING_WITHDRAWAL_SALVAGE_DEFER thread_id={thread_id}"
                    )
                    continue
                hours_label = (
                    f"{hrs_until:.1f}h_remaining" if hrs_until is not None else "no_datetime"
                )
                logger.info(f"VIEWING_CANCEL_NOW thread_id={thread_id} reason={hours_label}")
                cancelled = await _cancel_viewing_and_handoff(
                    thread_id, messages, latest_landlord_message, page
                )
                if not cancelled:
                    logger.warning(f"VIEWING_CANCEL_FAILED thread_id={thread_id}")
            elif block_reason:
                logger.info(
                    f"CANCELLATION_BLOCKED thread_id={thread_id} reason={block_reason}"
                )
            elif not phone_requested:
                # 2-step: ask for the landlord's number one run before withdrawing.
                travel_city = get_travel_city(thread_id)
                logger.info(f"PRE_CANCEL_NUMBER_ASK thread_id={thread_id}")
                await _send_pre_cancel_number_ask(
                    thread_id, messages, latest_landlord_message, page,
                    travel_city=travel_city,
                )
            else:
                logger.info(
                    f"VIEWING_CANCEL_WAITING thread_id={thread_id} "
                    f"phone_ask_age={phone_ask_age_h:.1f}h"
                )

            await random_sleep(2, 5)

        except Exception as exc:
            logger.exception(f"Cancellation failed for {thread_id}: {exc}")
            update_conversation_status(thread_id, AI_FAILED)

        finally:
            release_conversation_claim(thread_id, owner)


async def process_viewing_reminders():
    accounts = get_active_accounts()

    for account in accounts:
        playwright = None
        browser = None
        phase = "cancellations_only"

        try:
            update_account_worker_state(account.id, "running", phase=phase)
            playwright, browser, context, page = await launch_browser(account)
            await login(page, context, account)
            await process_account_viewing_reminders(account, page)
        except Exception as exc:
            logger.exception(
                f"Standalone viewing reminder worker failed for {account.email}: {exc}"
            )
            update_account_worker_state(
                account.id,
                "error",
                phase=phase,
                error=str(exc),
            )
        finally:
            if browser:
                await browser.close()
            if playwright:
                await playwright.stop()
            update_account_worker_state(account.id, "idle", phase=phase)


if __name__ == "__main__":
    init_db()
    asyncio.run(process_viewing_reminders())
