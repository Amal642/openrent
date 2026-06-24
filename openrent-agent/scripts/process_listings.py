
import random
from app.db.repository import (
    account_stop_requested,
    create_conversation,
    get_uncontacted_listings,
    mark_listing_contacted,
    mark_listing_failed,
    mark_listing_skipped,
    save_message_url,
    save_listing_metadata,
    can_send_message,
    increment_message_count,
    get_conversation_by_thread_id,
    claim_uncontacted_listings,
    ensure_account_persona,
    release_listing_claim,
    save_message_once,
    is_outreach_due,
    set_next_outreach_at,
)

from app.openrent.popups import (close_popups, handle_confirmation_popups)
from app.openrent.messaging import (
    extract_thread_id,
    open_listing,
    can_contact_landlord,
    get_message_link,
    send_initial_message,
    get_existing_thread_id,
)
from app.openrent.listing_metadata import extract_listing_metadata

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
    # Check outreach window FIRST — before any DB claims or browser work.
    if not is_uk_outreach_window():
        logger.info(
            f"OUTREACH_WINDOW_BLOCKED account_id={account.id} "
            f"email={account.email}"
        )
        return

    if not can_send_message(account.id):
        logger.info(
            f"DAILY LIMIT REACHED for {account.email} — skipping outreach"
        )
        return

    # Outreach is paced separately from the worker cooldown so new initial
    # messages spread across the whole operating day (1-3h random gap)
    # instead of bursting out the daily quota in the first run or two.
    # Reply-checking (process_account_replies, run before this) is unaffected
    # and keeps running on its own fast cooldown.
    if not is_outreach_due(account.id):
        logger.info(
            f"OUTREACH_NOT_DUE account_id={account.id} email={account.email} "
            "waiting for next_outreach_at — skipping new outreach this run"
        )
        return

    persona = ensure_account_persona(account.id)
    listings = claim_uncontacted_listings(
        account.id,
        worker_id or f"account-{account.id}",
        limit=20,
    )

    logger.info(
        f"MESSAGE_CANDIDATES_AVAILABLE account_id={account.id} "
        f"claimed={len(listings)}"
    )

    if not listings:
        logger.warning(
            f"NO_CANDIDATES account_id={account.id} email={account.email} "
            "no uncontacted listings available for outreach"
        )
        return

    logger.info(f"MESSAGE_STAGE_STARTED account_id={account.id} candidates={len(listings)}")

    messages_sent = 0
    agent_skipped = 0
    skipped_other = 0
    not_contactable = 0

    for listing in listings:
        # Snapshot all primitives immediately — the ORM object becomes detached
        # once the session_scope in claim_uncontacted_listings closes.
        # All subsequent attribute access must go through these local variables.
        listing_pk = listing.id
        property_url = listing.property_url
        listing_ext_id = listing.listing_id

        try:
            if account_stop_requested(account.id):
                break

            await open_listing(page, property_url)

            existing_thread_id = await get_existing_thread_id(page)

            if existing_thread_id:

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

            is_agent = await landlord_is_agent(
                page,
                property_url,
            )

            if is_agent is None:
                logger.warning(
                    f"Skipping listing {listing_ext_id}: agent status unknown"
                )
                mark_listing_skipped(listing_pk, reason="agent_status_unknown")
                skipped_other += 1
                continue

            if is_agent:
                logger.info(f"Skipping agent landlord for listing {listing_ext_id}")
                mark_listing_skipped(listing_pk, reason="agent")
                agent_skipped += 1
                continue

            await open_listing(page, property_url)

            await random_sleep(2, 4)

            metadata = await extract_listing_metadata(page)
            save_listing_metadata(listing_pk, metadata)

            min_months = metadata.get("min_tenancy_months")
            if metadata.get("is_short_term") or (
                min_months is not None and min_months < 12
            ):
                logger.info(
                    f"SHORT_TERM_PROPERTY listing={listing_ext_id} "
                    f"min_tenancy_months={min_months} — skipping"
                )
                mark_listing_skipped(listing_pk, reason="SHORT_TERM_PROPERTY")
                skipped_other += 1
                continue

            message_link = await get_message_link(page)
            contactable = message_link is not None

            if not contactable:
                mark_listing_skipped(listing_pk, reason="not_contactable")
                not_contactable += 1
                continue

            if not can_send_message(account.id):
                logger.info(f"Daily limit reached for account {account.id}")
                break

            full_url = f"https://www.openrent.co.uk{message_link}"
            save_message_url(listing_pk, full_url)

            message_text, error = generate_initial_property_message(
                metadata,
                persona=persona,
            )

            if not message_text:
                logger.warning(f"Failed generating message: {error}")
                mark_listing_failed(listing_pk, reason="message_generation_failed")
                continue

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

            if not thread_id:
                logger.warning(
                    f"Initial send did not produce a thread for "
                    f"listing {listing_ext_id}; final_url={final_url}"
                )
                mark_listing_failed(listing_pk, reason="no_thread_returned")
                continue

            mark_listing_contacted(listing_pk, thread_id=thread_id)
            increment_message_count(account.id)
            messages_sent += 1

            create_conversation(
                thread_id=thread_id,
                listing_id=listing_pk,
                conversation_style=persona.get("conversation_style"),
            )
            update_conversation_status(thread_id, "INITIAL_MESSAGE_SENT")
            save_message_once(thread_id, "outbound", message_text)

            await handle_confirmation_popups(page)
            await page.wait_for_timeout(random.randint(3000, 7000))
            await close_popups(page)

            # Only send one new initial message per run — schedule the next
            # one 1-3h from now so outreach spreads across the operating day.
            set_next_outreach_at(account.id)
            break

        except Exception as e:
            logger.exception(
                f"Processing failed for listing {listing_ext_id} "
                f"(pk={listing_pk}): {e}"
            )
            mark_listing_failed(listing_pk, reason=f"{type(e).__name__}: {str(e)[:300]}")

        finally:
            release_listing_claim(
                listing_pk,
                worker_id or f"account-{account.id}",
            )

    logger.info(
        f"MESSAGES_SENT_THIS_RUN account_id={account.id} "
        f"sent={messages_sent} candidates={len(listings)} "
        f"agent_skipped={agent_skipped} not_contactable={not_contactable} "
        f"other_skipped={skipped_other}"
    )
    logger.info(f"MESSAGE_STAGE_FINISHED account_id={account.id}")
