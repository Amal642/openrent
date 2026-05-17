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
    get_active_accounts,
    update_account_worker_state,
)


def account_phase(account, now=None):
    now = now or datetime.utcnow()

    if now.weekday() == 6:
        return "reply_only"

    active_parity = 0 if now.weekday() in (0, 2, 4) else 1
    if account.id % 2 == active_parity:
        return "send_and_reply"

    return "reply_only"


async def run_account_worker(
    account
):
    worker_id = f"account-{account.id}-{uuid4().hex[:8]}"
    phase = account_phase(account)

    logger.info(
        f"Starting worker for "
        f"account {account.email} in {phase}"
    )
    update_account_worker_state(account.id, "running", phase=phase)

    playwright = None
    browser = None

    try:

        playwright, browser, context, page = (
            await launch_browser(account)
        )

        await login(
            page,
            context,
            account
        )
        update_account_worker_state(account.id, "running", phase=phase)

        if phase == "send_and_reply":
            await process_account_listings(
                account,
                page,
                worker_id=worker_id
            )

        await process_account_replies(
            account,
            page,
            worker_id=worker_id
        )

        await process_account_viewing_reminders(
            account,
            page,
            worker_id=worker_id
        )

    except Exception as e:

        logger.exception(
            f"Worker failed for "
            f"{account.email}: {e}"
        )
        update_account_worker_state(account.id, "error", phase=phase, error=str(e))

    finally:

        if browser:
            await browser.close()

        if playwright:
            await playwright.stop()

        logger.info(
            f"Worker stopped for "
            f"{account.email}"
        )
        update_account_worker_state(account.id, "idle", phase=phase)


async def run_one_account_by_id(account_id):
    accounts = get_active_accounts()
    for account in accounts:
        if account.id == account_id:
            await run_account_worker(account)
            return

    logger.warning(f"Account {account_id} not found or inactive")
