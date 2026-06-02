import asyncio
from contextlib import suppress
from datetime import datetime
from uuid import uuid4

from app.utils.logger import logger

from app.browser.launcher import (
    launch_browser
)

from app.browser.auth import (
    login
)

from scripts.process_listings import (
    process_account_listings
)

from scripts.process_replies import (
    process_account_replies
)

from scripts.process_viewing_reminders import (
    process_account_viewing_reminders
)

from app.db.repository import (
    account_stop_requested,
    get_active_accounts,
    update_account_worker_state,
)

from app.queue.queues import worker_queue
from app.workers.rq_worker import run_account_worker_sync


ACTIVE_WORKERS = {}
ACTIVE_BROWSER_RESOURCES = {}


def account_phase(account, now=None):
    now = now or datetime.utcnow()

    if now.weekday() == 6:
        return "reply_only"

    active_parity = 0 if now.weekday() in (0, 2, 4) else 1

    if account.id % 2 == active_parity:
        return "send_and_reply"

    return "reply_only"


async def run_account_worker(account):

    worker_id = f"account-{account.id}-{uuid4().hex[:8]}"
    phase = account_phase(account)

    logger.info(
        f"Starting worker for "
        f"account {account.email} in {phase}"
    )

    update_account_worker_state(
        account.id,
        "running",
        phase=phase
    )

    playwright = None
    browser = None
    context = None

    try:

        playwright, browser, context, page = (
            await launch_browser(account)
        )

        ACTIVE_BROWSER_RESOURCES[account.id] = {
            "playwright": playwright,
            "browser": browser,
            "context": context,
        }

        await login(
            page,
            context,
            account
        )

        update_account_worker_state(
            account.id,
            "running",
            phase=phase
        )

        # =====================================================
        # STOP CHECK BEFORE LISTING PROCESSING
        # =====================================================

        if account_stop_requested(account.id):

            logger.info(
                f"Worker stop requested before "
                f"listing phase for {account.email}"
            )

            phase = "stopped"
            return

        # =====================================================
        # INITIAL OUTREACH PHASE
        # =====================================================

        if phase == "send_and_reply":

            await process_account_listings(
                account,
                page,
                worker_id=worker_id
            )

        # =====================================================
        # STOP CHECK BEFORE REPLY PROCESSING
        # =====================================================

        if account_stop_requested(account.id):

            logger.info(
                f"Worker stop requested before "
                f"reply phase for {account.email}"
            )

            phase = "stopped"
            return

        # =====================================================
        # AI REPLY PROCESSING PHASE
        # =====================================================

        await process_account_replies(
            account,
            page,
            worker_id=worker_id
        )

        # =====================================================
        # STOP CHECK BEFORE REMINDER PROCESSING
        # =====================================================

        if account_stop_requested(account.id):

            logger.info(
                f"Worker stop requested before "
                f"reminder phase for {account.email}"
            )

            phase = "stopped"
            return

        # =====================================================
        # VIEWING REMINDER PHASE
        # =====================================================

        await process_account_viewing_reminders(
            account,
            page,
            worker_id=worker_id
        )

        # =====================================================
        # SUCCESSFUL COMPLETION
        # =====================================================

        update_account_worker_state(
            account.id,
            "completed",
            phase="completed"
        )

    except asyncio.CancelledError:

        logger.info(
            f"Worker cancellation requested "
            f"for {account.email}"
        )

        phase = "stopped"

        update_account_worker_state(
            account.id,
            "idle",
            phase="stopped"
        )

        raise

    except Exception as e:

        logger.exception(
            f"Worker failed for "
            f"{account.email}: {e}"
        )

        update_account_worker_state(
            account.id,
            "error",
            phase=phase,
            error=str(e)
        )

    finally:

        ACTIVE_BROWSER_RESOURCES.pop(
            account.id,
            None
        )

        if context:
            with suppress(Exception):
                await context.close()

        if browser:
            with suppress(Exception):
                await browser.close()

        if playwright:
            with suppress(Exception):
                await playwright.stop()

        logger.info(
            f"Worker stopped for "
            f"{account.email}"
        )

        current_task = asyncio.current_task()

        if ACTIVE_WORKERS.get(account.id) is current_task:
            ACTIVE_WORKERS.pop(account.id, None)

        update_account_worker_state(
            account.id,
            "idle",
            phase=phase
        )


async def run_one_account_by_id(account_id):

    accounts = get_active_accounts()

    for account in accounts:

        if account.id == account_id:
            await run_account_worker(account)
            return

    logger.warning(
        f"Account {account_id} not found or inactive"
    )


def _forget_worker(account_id):

    def cleanup(task):

        if ACTIVE_WORKERS.get(account_id) is task:
            ACTIVE_WORKERS.pop(account_id, None)

        if task.cancelled():

            logger.info(
                f"Worker task for account "
                f"{account_id} cancelled"
            )

            return

        error = task.exception()

        if error:

            logger.error(
                f"Worker task for account "
                f"{account_id} ended with error: {error}"
            )

    return cleanup


# =========================================================
# REDIS / RQ BASED WORKER START
# =========================================================

async def start_account_worker(account_id):

    logger.info(
        f"Queueing worker for account {account_id}"
    )

    update_account_worker_state(
        account_id,
        "queued",
        phase="queued"
    )

    job = worker_queue.enqueue(
        run_account_worker_sync,
        account_id,
        job_timeout="2h"
    )

    logger.info(
        f"RQ job {job.id} queued "
        f"for account {account_id}"
    )

    return {
        "queued": True,
        "job_id": job.id
    }


# =========================================================
# STOP WORKER
# =========================================================

async def stop_account_worker(account_id):

    logger.info(
        f"Stopping worker for account {account_id}"
    )

    update_account_worker_state(
        account_id,
        "stopping",
        phase="stopping"
    )

    resources = ACTIVE_BROWSER_RESOURCES.get(account_id) or {}

    browser = resources.get("browser")
    context = resources.get("context")
    playwright = resources.get("playwright")

    if context:
        with suppress(Exception):
            await context.close()

    if browser:
        with suppress(Exception):
            await browser.close()

    if playwright:
        with suppress(Exception):
            await playwright.stop()

    ACTIVE_WORKERS.pop(account_id, None)

    ACTIVE_BROWSER_RESOURCES.pop(account_id, None)

    update_account_worker_state(
        account_id,
        "idle",
        phase="stopped"
    )

    logger.info(
        f"Worker stopped for account {account_id}"
    )

    return True


def get_active_worker_count():

    return len([
        task
        for task in ACTIVE_WORKERS.values()
        if not task.done()
    ])