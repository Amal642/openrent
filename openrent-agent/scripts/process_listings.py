
import random
from app.db.repository import (
    account_stop_requested,
    create_conversation,
    get_uncontacted_listings,
    mark_listing_contacted,
    mark_listing_failed,
    mark_listing_skipped,
    save_message_url,
    can_send_message,
    increment_message_count,
    get_conversation_by_thread_id,
    claim_uncontacted_listings,
    ensure_account_persona,
    release_listing_claim,
    save_message_once,
)

from app.openrent.popups import (close_popups, handle_confirmation_popups)
from app.openrent.messaging import (
    extract_thread_id,
    open_listing,
    can_contact_landlord,
    get_message_link,
    send_initial_message,
    get_existing_thread_id,
    extract_listing_metadata
)

from app.ai.replies import (
    generate_initial_property_message
)

from app.db.repository import update_conversation_status

from app.utils.human import random_sleep
from app.utils.scheduling import is_uk_outreach_window

from app.utils.logger import logger

from app.openrent.landlords import landlord_is_agent

async def process_account_listings(
    account,
    page,
    worker_id=None
):

   

    persona = ensure_account_persona(account.id)
    listings = claim_uncontacted_listings(
        account.id,
        worker_id or f"account-{account.id}",
        limit=5
    )

    if not listings:
        print("No listings to process")
        logger.warning("No listings to process")
        return



    for listing in listings:

        try:
            if account_stop_requested(account.id):
                logger.info(
                    f"Listing processing stopped for account {account.id}"
                )
                break

            await open_listing(page, listing)

            existing_thread_id = await get_existing_thread_id(page)

            if existing_thread_id:

                print(
                    f"Already enquired. Thread ID: {existing_thread_id}"
                )

                mark_listing_contacted(
                    listing.id,
                    thread_id=existing_thread_id
                )

                existing_conversation = get_conversation_by_thread_id(
                    existing_thread_id
                )

                if not existing_conversation:

                    create_conversation(
                        thread_id=existing_thread_id,
                        listing_id=listing.id,
                        conversation_style=persona.get("conversation_style"),
                    )

                    update_conversation_status(
                        existing_thread_id,
                        "INITIAL_MESSAGE_SENT"
                    )

                continue

            await random_sleep(2, 5)
            is_agent = await landlord_is_agent(
                page,
                listing.property_url,
            )

            if is_agent is None:
                logger.warning(
                    "Skipping listing because landlord agent status is unknown"
                )
                mark_listing_skipped(
                    listing.id,
                    reason="agent_status_unknown",
                )
                continue

            if is_agent:

                logger.info(
                    "Skipping agent landlord"
                )

                mark_listing_skipped(
                    listing.id,
                    reason="agent",
                )

                continue
            # reopen original listing page
            await open_listing(page, listing)

            await random_sleep(2, 4)
            
            metadata = await extract_listing_metadata(
                page
            )

            print("Listing metadata:", metadata)

            message_link = await get_message_link(page)

            contactable = message_link is not None

            print(
                f"Listing {listing.listing_id} "
                f"contactable: {contactable}"
            )
            logger.info(f"Listing {listing.listing_id} contactable: {contactable}")

            if not contactable:
                mark_listing_skipped(
                    listing.id,
                    reason="not_contactable",
                )
                continue

            if not can_send_message(account.id):

                print("Daily limit reached")
                logger.info(f"Daily limit reached for account {account.id}")
                break

            if not is_uk_outreach_window():
                logger.info(
                    "Outside UK outreach window; stopping initial enquiries "
                    f"for account {account.id}"
                )
                break

            full_url = f"https://www.openrent.co.uk{message_link}"

            save_message_url(
                listing.id,
                full_url
            )

            print("Message route saved:", full_url)
            logger.info(f"Message route saved: {full_url}")

            # Initial message generation stage: create a persona-aware opener
            # before touching the OpenRent send path.
            logger.info(
                f"Generating initial message for listing {listing.listing_id}"
            )
            message_text, error = (
                generate_initial_property_message(
                    metadata,
                    persona=persona
                )
            )

            if not message_text:

                logger.warning(
                    f"Failed generating message: {error}"
                )

                mark_listing_failed(
                    listing.id
                )

                continue

            print("Generated message:")
            print(message_text)
            logger.info(
                f"Initial message generated for listing {listing.listing_id}: "
                f"{message_text}"
            )

            # Initial outbound send stage: only mark the listing contacted after
            # OpenRent returns a thread URL that can be persisted.
            final_url = await send_initial_message(
                page=page,
                message_url=full_url,
                message_text=message_text,
                metadata=metadata
            )

            thread_id = extract_thread_id(final_url)
            if not thread_id:
                existing_thread_id = await get_existing_thread_id(page)
                thread_id = existing_thread_id or extract_thread_id(page.url)

            print("Extracted thread ID:", thread_id)
            logger.info(f"Extracted thread ID: {thread_id}")

            if not thread_id:
                logger.warning(
                    f"Initial send did not produce a thread for "
                    f"listing {listing.listing_id}; final_url={final_url}"
                )
                mark_listing_failed(listing.id)
                continue

            mark_listing_contacted(
                listing.id,
                thread_id=thread_id
            )

            increment_message_count(account.id)

            if thread_id:

                create_conversation(
                    thread_id=thread_id,
                    listing_id=listing.id,
                    conversation_style=persona.get("conversation_style"),
                )
                update_conversation_status(thread_id, "INITIAL_MESSAGE_SENT")
                save_message_once(thread_id, "outbound", message_text)
                logger.info(
                    f"Initial outbound message persisted for thread {thread_id}"
                )

                print("Conversation created")
                await handle_confirmation_popups(page)

            delay = random.randint(3000, 7000)

            await page.wait_for_timeout(delay)
            await close_popups(page)
        except Exception as e:

            print("Processing failed:", e)
            logger.exception(f"Processing failed for listing {listing.id}: {e}")

            mark_listing_failed(listing.id)
        finally:
            release_listing_claim(
                listing.id,
                worker_id or f"account-{account.id}"
            )
