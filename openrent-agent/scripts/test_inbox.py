import asyncio

from app.db.repository import get_active_accounts

from app.browser.launcher import launch_browser
from app.browser.auth import login

from app.openrent.inbox import (
    get_all_reply_threads
)


async def main():

    accounts = get_active_accounts()

    if not accounts:
        print("No accounts found")
        return

    account = accounts[0]

    playwright, browser, context, page = await launch_browser(account)

    try:

        await login(page, context, account)

        threads = await get_all_reply_threads(page)

        print(
            f"\nFound {len(threads)} "
            f"landlord reply threads\n"
        )

        for thread in threads:

            print(thread)

    finally:

        await browser.close()
        await playwright.stop()


if __name__ == "__main__":
    asyncio.run(main())