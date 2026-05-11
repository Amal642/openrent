import asyncio
import random
from turtle import delay
from app.db.repository import (
    create_conversation,
    get_active_accounts,
    get_uncontacted_listings,
    mark_listing_contacted,
    mark_listing_failed,
    save_message_url,
    can_send_message,
    increment_message_count
)

from app.browser.launcher import launch_browser
from app.browser.auth import login

from app.openrent.messaging import (
    extract_thread_id,
    open_listing,
    can_contact_landlord,
    get_message_link,
    send_initial_message
)

from app.utils.human import random_sleep

from app.utils.logger import logger

from app.openrent.landlords import landlord_is_agent

async def main():

    accounts = get_active_accounts()

    if not accounts:
        print("No accounts found")
        logger.warning("No active accounts found in database")
        return

    account = accounts[0]

    listings = get_uncontacted_listings(limit=5)

    if not listings:
        print("No listings to process")
        logger.warning("No listings to process")
        return

    playwright, browser, context, page = await launch_browser(account)

    try:

        await login(page, context, account)

        for listing in listings:

            try:

                await open_listing(page, listing)

                await random_sleep(2, 5)
                is_agent = await landlord_is_agent(
                    page
                )

                if is_agent:

                    logger.info(
                        "Skipping agent landlord"
                    )

                    mark_listing_failed(
                        listing.id
                    )

                    continue
                message_link = await get_message_link(page)

                contactable = message_link is not None

                print(
                    f"Listing {listing.listing_id} "
                    f"contactable: {contactable}"
                )
                logger.info(f"Listing {listing.listing_id} contactable: {contactable}")

                if not contactable:
                    continue

                if not can_send_message(account.id):

                    print("Daily limit reached")
                    logger.exception(f"Daily limit reached for account {account.id}")
                    break

                full_url = f"https://www.openrent.co.uk{message_link}"

                save_message_url(
                    listing.id,
                    full_url
                )

                print("Message route saved:", full_url)
                logger.info(f"Message route saved: {full_url}")

                final_url = await send_initial_message(
                    page=page,
                    message_url=full_url,
                    message_text=account.initial_message
                )

                thread_id = extract_thread_id(final_url)

                print("Extracted thread ID:", thread_id)
                logger.info(f"Extracted thread ID: {thread_id}")

                mark_listing_contacted(
                    listing.id,
                    thread_id=thread_id
                )

                increment_message_count(account.id)

                if thread_id:

                    create_conversation(
                        thread_id=thread_id,
                        listing_id=listing.id
                    )

                    print("Conversation created")

                delay = random.randint(3000, 7000)

                await page.wait_for_timeout(delay)
            except Exception as e:

                print("Processing failed:", e)
                logger.exception(f"Processing failed for listing {listing.id}: {e}")

                mark_listing_failed(listing.id)

    finally:

        await browser.close()
        await playwright.stop()


if __name__ == "__main__":
    asyncio.run(main())