
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
    claim_overflow_listings,
    overflow_listing_fits_band,
    return_overflow_listing,
    ensure_account_persona,
    release_listing_claim,
    save_message_once,
    is_outreach_due,
    set_next_outreach_at,
    landlord_already_contacted,
    mark_listing_early_access,
)

from app.openrent.popups import (close_popups, handle_confirmation_popups)
from app.openrent.messaging import (
    extract_thread_id,
    open_listing,
    can_contact_landlord,
    get_message_link,
    send_initial_message,
    get_existing_thread_id,
    EarlyAccessRestricted,
)
from app.services import page_health
from app.db.repository import EARLY_ACCESS_CLAIM_LIMIT

from datetime import datetime

# Listings newer than the account's own newest that it may take per run.
FRESH_CLAIM_LIMIT = 4
from app.openrent.listing_metadata import (
    MIN_ACCEPTED_TENANCY_MONTHS,
    extract_listing_metadata,
)

from app.ai.replies import (
    generate_initial_property_message
)

from app.db.repository import update_conversation_status

from app.utils.human import random_sleep
from app.utils.scheduling import is_uk_outreach_window

from app.utils.logger import logger
from app.alerts.events import report_error

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

    # Fleet-wide pause: the enquiry form has been failing on several accounts
    # at once (OpenRent changed the page). Don't keep loading a broken form;
    # the alert bot lifts this once the form works again.
    breaker = page_health.breaker_state(page_health.OUTREACH)
    if breaker:
        logger.warning(
            f"OUTREACH_PAUSED_BREAKER account_id={account.id} "
            f"until={breaker.get('until')} reason={breaker.get('reason')!r}"
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
    claim_owner = worker_id or f"account-{account.id}"

    # Early-access listings other accounts were blocked from (Verified Tenants
    # only). They are the freshest listings with the fewest competing
    # enquiries, so an account not known to be blocked tries them first. Not
    # sent this run = handed back to the owner like any overflow listing.
    early_listings, overflow_origin = claim_overflow_listings(
        account.id, claim_owner, limit=EARLY_ACCESS_CLAIM_LIMIT, early_access_only=True
    )
    if early_listings:
        logger.info(
            f"EARLY_ACCESS_CLAIMED account_id={account.id} claimed={len(early_listings)} "
            f"donors={sorted({o['origin_account_id'] for o in overflow_origin.values()})}"
        )

    own_listings = claim_uncontacted_listings(
        account.id,
        claim_owner,
        limit=20,
    )

    # Freshest first: listings in our region newer than our own newest, even
    # if another account found them. Earlier enquiries get more replies
    # (first 3 days ~42% vs ~33% after), and accounts with a local backlog
    # were sending 10-27h-old listings while fresh ones sat elsewhere.
    # Same one send per run; anything unsent goes back to its finder.
    newest_own = max(
        (l.first_seen for l in own_listings if getattr(l, "first_seen", None)), default=None
    )
    fresh_listings, fresh_origin = claim_overflow_listings(
        account.id, claim_owner, limit=FRESH_CLAIM_LIMIT, freshest=True, newer_than=newest_own
    )
    if fresh_listings:
        overflow_origin.update(fresh_origin)
        logger.info(
            f"FRESHER_CLAIMED account_id={account.id} claimed={len(fresh_listings)} "
            f"own_newest={newest_own} "
            f"donors={sorted({o['origin_account_id'] for o in fresh_origin.values()})}"
        )

    listings = early_listings + sorted(
        fresh_listings + own_listings,
        key=lambda l: getattr(l, "first_seen", None) or datetime.min,
        reverse=True,
    )

    # No inventory of our own: take over surplus listings from same-region
    # accounts that can't send them all (see claim_overflow_listings). Each
    # one is rent-checked against our persona's band once its page is open,
    # and anything not sent this run goes back to its donor.
    if not listings:
        listings, overflow_origin = claim_overflow_listings(account.id, claim_owner)
        if listings:
            donors = sorted({o["origin_account_id"] for o in overflow_origin.values()})
            logger.info(
                f"OVERFLOW_CLAIMED account_id={account.id} "
                f"claimed={len(listings)} donors={donors}"
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

    try:
        messages_sent, agent_skipped, skipped_other, not_contactable = await _process_claimed_listings(
            account, page, listings, persona, claim_owner, overflow_origin
        )
    finally:
        for listing_pk, origin in overflow_origin.items():
            return_overflow_listing(
                listing_pk, origin["origin_profile_id"], claim_owner, reason="end_of_run"
            )

    logger.info(
        f"MESSAGES_SENT_THIS_RUN account_id={account.id} "
        f"sent={messages_sent} candidates={len(listings)} "
        f"agent_skipped={agent_skipped} not_contactable={not_contactable} "
        f"other_skipped={skipped_other}"
    )
    logger.info(f"MESSAGE_STAGE_FINISHED account_id={account.id}")


async def _process_claimed_listings(account, page, listings, persona, claim_owner, overflow_origin):
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
                listing_id=listing_pk,
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

            # Fleet-wide landlord dedup: landlord_is_agent above just linked this
            # listing to its landlord. If we've already messaged that landlord via
            # another listing, skip this one — one landlord = one persona = one
            # thread, so a landlord never sees contradictory enquiries across their
            # listings (the "are you a scammer?" case). Best-effort: any failure
            # falls through to normal contact, never blocking discovery.
            try:
                if landlord_already_contacted(listing_pk):
                    logger.info(
                        f"LANDLORD_DEDUP_SKIP listing={listing_ext_id} "
                        "— landlord already contacted via another listing"
                    )
                    mark_listing_skipped(listing_pk, reason="landlord_already_contacted")
                    skipped_other += 1
                    continue
            except Exception as exc:
                logger.warning(
                    f"landlord dedup check failed listing={listing_pk}: {exc}"
                )

            await open_listing(page, property_url)

            await random_sleep(2, 4)

            metadata = await extract_listing_metadata(page)
            save_listing_metadata(listing_pk, metadata)

            min_months = metadata.get("min_tenancy_months")
            if metadata.get("is_short_term") or (
                min_months is not None and min_months < MIN_ACCEPTED_TENANCY_MONTHS
            ):
                logger.info(
                    f"SHORT_TERM_PROPERTY listing={listing_ext_id} "
                    f"min_tenancy_months={min_months} — skipping"
                )
                mark_listing_skipped(listing_pk, reason="SHORT_TERM_PROPERTY")
                skipped_other += 1
                continue

            overflow = overflow_origin.get(listing_pk)
            if overflow and not overflow_listing_fits_band(metadata, overflow):
                logger.info(
                    f"OVERFLOW_OUT_OF_BAND listing={listing_ext_id} "
                    f"rent_pcm={metadata.get('rent_pcm')} bedrooms={metadata.get('bedrooms')} "
                    f"band=£{overflow['price_min']}-{overflow['price_max']} — returning to donor"
                )
                return_overflow_listing(
                    listing_pk, overflow["origin_profile_id"], claim_owner, reason="out_of_band"
                )
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
            try:
                final_url = await send_initial_message(
                    page=page,
                    message_url=full_url,
                    message_text=message_text,
                    metadata=metadata,
                    persona=persona,
                )
            except EarlyAccessRestricted as blocked:
                # Not a failure: this account isn't a Verified Tenant. Leave
                # the listing open for accounts that are, and for this one
                # once OpenRent's countdown says it unlocks.
                logger.info(
                    f"EARLY_ACCESS_BLOCKED listing={listing_ext_id} account_id={account.id} "
                    f"unlock_in_minutes={blocked.unlock_in_minutes} — left open for verified accounts"
                )
                mark_listing_early_access(listing_pk, account.id, blocked.unlock_in_minutes)
                skipped_other += 1
                continue

            thread_id = extract_thread_id(final_url)
            if not thread_id:
                existing_thread_id = await get_existing_thread_id(page)
                thread_id = existing_thread_id or extract_thread_id(page.url)

            if not thread_id:
                logger.warning(
                    f"Initial send did not produce a thread for "
                    f"listing {listing_ext_id}; final_url={final_url}"
                )
                page_health.record_step(
                    page_health.ENQUIRY_SUBMIT, False, f"no thread id after submit, url={final_url}"
                )
                mark_listing_failed(listing_pk, reason="no_thread_returned")
                continue

            page_health.record_step(page_health.ENQUIRY_SUBMIT, True)

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
            report_error(
                "scraper",
                "Listing processing failed",
                context={"listing_id": listing_pk, "listing_ext_id": listing_ext_id, "account_id": account.id},
                exc=e,
            )

        finally:
            release_listing_claim(
                listing_pk,
                claim_owner,
            )

    return messages_sent, agent_skipped, skipped_other, not_contactable
