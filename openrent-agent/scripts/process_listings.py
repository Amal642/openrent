import asyncio

from app.db.repository import (
    get_active_accounts,
    get_uncontacted_listings,
    mark_listing_failed
)

from app.browser.launcher import launch_browser
from app.browser.auth import login

from app.openrent.messaging import (
    open_listing,
    can_contact_landlord
)


async def main():

    accounts = get_active_accounts()

    if not accounts:
        print("No accounts found")
        return

    account = accounts[0]

    listings = get_uncontacted_listings(limit=5)

    if not listings:
        print("No listings to process")
        return

    playwright, browser, context, page = await launch_browser(account)

    try:

        await login(page, context, account)

        for listing in listings:

            try:

                await open_listing(page, listing)

                contactable = await can_contact_landlord(page)

                print(
                    f"Listing {listing.listing_id} "
                    f"contactable: {contactable}"
                )

            except Exception as e:

                print("Processing failed:", e)

                mark_listing_failed(listing.id)

    finally:

        await browser.close()
        await playwright.stop()


if __name__ == "__main__":
    asyncio.run(main())