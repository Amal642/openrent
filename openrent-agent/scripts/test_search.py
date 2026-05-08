import asyncio

from app.db.repository import get_active_accounts
from app.openrent.search import get_account_search_urls
from app.browser.launcher import launch_browser
from app.browser.auth import login
from app.openrent.listings import scrape_search_results


async def main():

    accounts = get_active_accounts()

    if not accounts:
        print("No active accounts found")
        return

    account = accounts[0]

    playwright, browser, context, page = await launch_browser(account)

    try:

        await login(page, context, account)

        urls = get_account_search_urls(account.id)

        for item in urls:

            await scrape_search_results(
                page=page,
                search_profile_id=item["profile_id"],
                search_url=item["url"]
            )

    finally:
        await browser.close()
        await playwright.stop()


if __name__ == "__main__":
    asyncio.run(main())