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


async def run_account_worker(
    account
):

    logger.info(
        f"Starting worker for "
        f"account {account.email}"
    )

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

        # Outbound
        await process_account_listings(
            account,
            page
        )

        # Inbox / AI
        await process_account_replies(
            account,
            page
        )

    except Exception as e:

        logger.exception(
            f"Worker failed for "
            f"{account.email}: {e}"
        )

    finally:

        if browser:
            await browser.close()

        if playwright:
            await playwright.stop()

        logger.info(
            f"Worker stopped for "
            f"{account.email}"
        )