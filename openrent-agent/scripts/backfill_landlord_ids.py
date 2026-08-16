"""One-time (repeatable) backfill of listings.landlord_id for legacy rows.

WHY: cross-listing landlord dedup (repository.landlord_already_contacted) keys on
landlord_id. Forward-linking at discovery works, but the ~3.3k listings messaged
BEFORE that wiring shipped are never re-processed, so they stay unlinked — and
the dedup needs the already-messaged sibling to be linked to fire. The hybrid
name+address fallback covers same-flat double-posts today; this backfill restores
the full landlord-identity signal (same landlord across DIFFERENT flats), which
name+address cannot catch.

HOW: OpenRent blocks non-browser requests (405), so we reuse the proven browser
path — landlord_is_agent(page, url, listing_id) extracts the landlord id off the
rent-info page and links it (attach_landlord_to_listing), using the 90-day agent
cache so known landlords cost a single page load. Runs under ONE active account's
own session + proxy so it looks like ordinary browsing.

GENTLE BY DESIGN: capped per run (--limit), extract_landlord_id already sleeps
2-5s + 3-6s per listing, and it never messages anyone. Idempotent: linked rows
drop out of the candidate set, so re-running just continues where it left off.

Usage:
    python -m scripts.backfill_landlord_ids --dry-run            # count + sample only
    python -m scripts.backfill_landlord_ids --limit 100          # link up to 100
    python -m scripts.backfill_landlord_ids --limit 100 --account-id 22
"""
import argparse
import asyncio

from app.browser.auth import login
from app.browser.launcher import launch_browser
from app.db.connection import SessionLocal
from app.db.init_db import init_db
from app.db.models import Account, Listing
from app.db.repository import get_active_accounts, update_account_worker_state
from app.openrent.landlords import landlord_is_agent
from app.utils.logger import logger


def _candidate_query(db):
    """Legacy rows worth linking: already messaged, not yet linked, has a URL.
    Newest first so the most relevant recent leads get identity soonest."""
    return (
        db.query(Listing)
        .filter(
            Listing.message_sent == True,  # noqa: E712
            Listing.landlord_id.is_(None),
            Listing.property_url.isnot(None),
        )
        .order_by(Listing.id.desc())
    )


def _load_candidates(limit):
    with SessionLocal() as db:
        q = _candidate_query(db)
        total = q.count()
        rows = q.limit(limit).all()
        # Snapshot primitives — objects detach once the session closes.
        items = [(r.id, r.property_url, r.listing_id, r.landlord_name) for r in rows]
    return total, items


def _pick_account(account_id):
    accounts = get_active_accounts()
    if not accounts:
        return None
    if account_id is not None:
        for a in accounts:
            if a.id == account_id:
                return a
        return None
    return accounts[0]


async def backfill(limit, account_id, dry_run):
    total, items = _load_candidates(limit)
    logger.info(
        f"BACKFILL_LANDLORD_IDS candidates_total={total} this_run={len(items)} "
        f"dry_run={dry_run}"
    )
    if dry_run:
        for pk, url, ext, name in items[:15]:
            logger.info(f"  candidate listing_pk={pk} ext={ext} name={name!r} url={url}")
        print(f"[dry-run] {total} unlinked messaged listings; would process {len(items)} now.")
        return

    if not items:
        print("Nothing to backfill — all messaged listings are already linked.")
        return

    account = _pick_account(account_id)
    if account is None:
        print("No usable active account found (check --account-id).")
        return

    playwright = browser = None
    linked = failed = 0
    try:
        update_account_worker_state(account.id, "running", phase="landlord_id_backfill")
        playwright, browser, context, page = await launch_browser(account)
        await login(page, context, account)
        logger.info(
            f"BACKFILL_START account_id={account.id} email={account.email} "
            f"batch={len(items)}"
        )

        for idx, (pk, url, ext, name) in enumerate(items, 1):
            try:
                # landlord_is_agent extracts the landlord id and links it
                # (attach_landlord_to_listing) on both cache-hit and scan paths.
                await landlord_is_agent(page, url, listing_id=pk)
                # Confirm the link actually landed.
                with SessionLocal() as db:
                    row = db.query(Listing).filter(Listing.id == pk).first()
                    ok = row is not None and row.landlord_id is not None
                if ok:
                    linked += 1
                else:
                    failed += 1
                    logger.warning(f"BACKFILL_NO_LINK listing_pk={pk} ext={ext} url={url}")
                if idx % 10 == 0:
                    logger.info(
                        f"BACKFILL_PROGRESS {idx}/{len(items)} linked={linked} failed={failed}"
                    )
            except Exception as exc:
                failed += 1
                logger.warning(f"BACKFILL_ITEM_FAILED listing_pk={pk} error={exc}")
    except Exception as exc:
        logger.exception(f"BACKFILL_WORKER_FAILED account={getattr(account,'email',None)}: {exc}")
    finally:
        if browser:
            await browser.close()
        if playwright:
            await playwright.stop()
        update_account_worker_state(account.id, "idle", phase="landlord_id_backfill")

    remaining = max(0, total - linked)
    logger.info(f"BACKFILL_DONE linked={linked} failed={failed} remaining={remaining}")
    print(f"Backfill done: linked={linked} failed={failed} remaining~{remaining}")


def main():
    p = argparse.ArgumentParser(description="Backfill listings.landlord_id for legacy rows")
    p.add_argument("--limit", type=int, default=100, help="max listings to process this run")
    p.add_argument("--account-id", type=int, default=None, help="active account to browse under")
    p.add_argument("--dry-run", action="store_true", help="count + sample candidates, no browser")
    args = p.parse_args()

    init_db()
    asyncio.run(backfill(args.limit, args.account_id, args.dry_run))


if __name__ == "__main__":
    main()
