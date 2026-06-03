
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
    logger.info("=" * 60)
    logger.info("PROCESSING INITIAL OUTREACH")
    logger.info(f"ACCOUNT: {account.email} (id={account.id})")

    if not can_send_message(account.id):
        logger.info(
            f"DAILY LIMIT REACHED for {account.email} — skipping outreach"
        )
        return

    persona = ensure_account_persona(account.id)
    listings = claim_uncontacted_listings(
        account.id,
        worker_id or f"account-{account.id}",
        limit=5
    )

    logger.info(
        f"UNCONTACTED LISTINGS CLAIMED: {len(listings)} "
        f"(account {account.email})"
    )

    if not listings:
        logger.warning(
            f"NO LISTINGS TO PROCESS for {account.email}. "
            "If scraping just ran, check debug/ artifacts for why 0 listings were found."
        )
        return



    for listing in listings:
        # Snapshot all primitives immediately — the ORM object becomes detached
        # once the session_scope in claim_uncontacted_listings closes.
        # All subsequent attribute access must go through these local variables.
        listing_pk = listing.id
        property_url = listing.property_url
        listing_ext_id = listing.listing_id

        try:
            if account_stop_requested(account.id):
                logger.info(
                    f"Listing processing stopped for account {account.id}"
                )
                break

            logger.info(f"Opening listing: {property_url}")
            await open_listing(page, property_url)

            existing_thread_id = await get_existing_thread_id(page)

            if existing_thread_id:

                logger.info(f"Already enquired. Thread ID: {existing_thread_id}")

                mark_listing_contacted(
                    listing_pk,
                    thread_id=existing_thread_id,
                )

                existing_conversation = get_conversation_by_thread_id(
                    existing_thread_id
                )

                if not existing_conversation:

                    create_conversation(
                        thread_id=existing_thread_id,
                        listing_id=listing_pk,
                        conversation_style=persona.get("conversation_style"),
                    )

                    update_conversation_status(
                        existing_thread_id,
                        "INITIAL_MESSAGE_SENT",
                    )

                continue

            await random_sleep(2, 5)

            logger.info(f"Checking agent status for listing {listing_ext_id}")
            is_agent = await landlord_is_agent(
                page,
                property_url,
            )

            if is_agent is None:
                logger.warning(
                    f"Skipping listing {listing_ext_id}: agent status unknown"
                )
                mark_listing_skipped(listing_pk, reason="agent_status_unknown")
                continue

            if is_agent:
                logger.info(f"Skipping agent landlord for listing {listing_ext_id}")
                mark_listing_skipped(listing_pk, reason="agent")
                continue

            # Reopen the original listing page after agent check navigation
            logger.info(f"Reopening listing page: {property_url}")
            await open_listing(page, property_url)

            await random_sleep(2, 4)

            metadata = await extract_listing_metadata(page)
            logger.info(f"Listing metadata: {metadata}")

            message_link = await get_message_link(page)
            contactable = message_link is not None
            logger.info(f"Listing {listing_ext_id} contactable: {contactable}")

            if not contactable:
                mark_listing_skipped(listing_pk, reason="not_contactable")
                continue

            if not can_send_message(account.id):
                logger.info(f"Daily limit reached for account {account.id}")
                break

            if not is_uk_outreach_window():
                logger.info(
                    "Outside UK outreach window; stopping initial enquiries "
                    f"for account {account.id}"
                )
                break

            full_url = f"https://www.openrent.co.uk{message_link}"
            save_message_url(listing_pk, full_url)
            logger.info(f"Message route saved: {full_url}")

            logger.info(f"Generating initial message for listing {listing_ext_id}")
            message_text, error = generate_initial_property_message(
                metadata,
                persona=persona,
            )

            if not message_text:
                logger.warning(f"Failed generating message: {error}")
                mark_listing_failed(listing_pk)
                continue

            logger.info(
                f"Initial message generated for listing {listing_ext_id}: "
                f"{message_text}"
            )

            # Send — only mark contacted after OpenRent returns a thread URL.
            final_url = await send_initial_message(
                page=page,
                message_url=full_url,
                message_text=message_text,
                metadata=metadata,
            )

            thread_id = extract_thread_id(final_url)
            if not thread_id:
                existing_thread_id = await get_existing_thread_id(page)
                thread_id = existing_thread_id or extract_thread_id(page.url)

            logger.info(f"Extracted thread ID: {thread_id}")

            if not thread_id:
                logger.warning(
                    f"Initial send did not produce a thread for "
                    f"listing {listing_ext_id}; final_url={final_url}"
                )
                mark_listing_failed(listing_pk)
                continue

            mark_listing_contacted(listing_pk, thread_id=thread_id)
            increment_message_count(account.id)

            create_conversation(
                thread_id=thread_id,
                listing_id=listing_pk,
                conversation_style=persona.get("conversation_style"),
            )
            update_conversation_status(thread_id, "INITIAL_MESSAGE_SENT")
            save_message_once(thread_id, "outbound", message_text)
            logger.info(
                f"Initial outbound message persisted for thread {thread_id}"
            )

            await handle_confirmation_popups(page)
            await page.wait_for_timeout(random.randint(3000, 7000))
            await close_popups(page)

        except Exception as e:
            logger.exception(
                f"Processing failed for listing {listing_ext_id} "
                f"(pk={listing_pk}): {e}"
            )
            mark_listing_failed(listing_pk)

        finally:
            release_listing_claim(
                listing_pk,
                worker_id or f"account-{account.id}",
            )
