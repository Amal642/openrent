import asyncio

from app.ai.replies import generate_cancellation_message
from app.browser.auth import login
from app.browser.launcher import launch_browser
from app.db.repository import (
    claim_conversation,
    get_active_accounts,
    get_automatic_cancellation_block_reason,
    get_due_viewing_cancellations,
    mark_viewing_cancelled,
    release_conversation_claim,
    save_message,
    update_account_worker_state,
    update_conversation_status,
)
from app.db.init_db import init_db
from app.db.status import AI_FAILED, VIEWING_CANCELLED
from app.openrent.inbox import extract_conversation, open_thread, send_reply
from app.utils.human import random_sleep
from app.utils.logger import logger


async def process_account_viewing_reminders(account, page, worker_id=None):
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

        # Pre-flight guard: all three conditions must hold before any cancellation
        # is sent.  The DB query already filters on these, but this is a last-line
        # defence in case a race condition or stale record slips through.
        viewing_datetime = viewing.get("viewing_datetime")
        viewing_confirmed = viewing.get("viewing_confirmed")
        conversation_stage = viewing.get("conversation_stage")

        if not viewing_datetime or not viewing_confirmed or conversation_stage != "VIEWING_BOOKED":
            logger.warning(
                f"CANCELLATION_BLOCKED thread_id={thread_id} "
                f"reason=no_confirmed_viewing_datetime "
                f"viewing_datetime={viewing_datetime} "
                f"viewing_confirmed={viewing_confirmed} "
                f"conversation_stage={conversation_stage}"
            )
            continue

        try:
            if not claim_conversation(thread_id, owner):
                logger.info(f"Cancellation skipped for claimed thread {thread_id}")
                continue

            await open_thread(page, thread_id)
            messages = await extract_conversation(page)

            block_reason = get_automatic_cancellation_block_reason(thread_id)
            if block_reason:
                logger.info(
                    f"CANCELLATION_BLOCKED thread_id={thread_id} "
                    f"reason={block_reason}"
                )
                continue

            message, error = generate_cancellation_message(messages)
            if not message or error:
                logger.warning(
                    f"Cancellation generation failed for {thread_id}: {error}"
                )
                update_conversation_status(thread_id, AI_FAILED)
                continue

            sent = await send_reply(page, message)
            if not sent:
                logger.warning(f"Cancellation send failed for {thread_id}")
                update_conversation_status(thread_id, AI_FAILED)
                continue

            save_message(thread_id, "outbound", message)
            mark_viewing_cancelled(thread_id)
            update_conversation_status(thread_id, VIEWING_CANCELLED)

            logger.info(f"Cancelled viewing for thread {thread_id}")
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
