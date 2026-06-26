"""
Daily background task: delete fetched listings that were never messaged
and are older than 30 days (OpenRent removes listings after ~21 days).

Only deletes rows where message_sent=False — never touches listings
that had an initial message sent.
"""
from __future__ import annotations

import asyncio
from contextlib import suppress

from app.db.repository import delete_stale_uncontacted_listings
from app.utils.logger import logger

_INTERVAL_SECONDS = 24 * 60 * 60  # run once per day
_STALE_DAYS = 30


async def _run_cleanup() -> None:
    deleted = await asyncio.to_thread(delete_stale_uncontacted_listings, _STALE_DAYS)
    if deleted:
        logger.info(f"LISTING_CLEANUP_CYCLE deleted={deleted} stale_days={_STALE_DAYS}")


async def _listing_cleanup_loop() -> None:
    # Small initial delay so the app finishes starting up first
    await asyncio.sleep(60)
    while True:
        try:
            await _run_cleanup()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception(f"LISTING_CLEANUP_FAILED error={exc}")
        await asyncio.sleep(_INTERVAL_SECONDS)


def start_listing_cleanup() -> asyncio.Task:
    logger.info(f"LISTING_CLEANUP_STARTED interval_hours=24 stale_days={_STALE_DAYS}")
    return asyncio.create_task(_listing_cleanup_loop(), name="listing-cleanup")


async def stop_listing_cleanup(task: asyncio.Task | None) -> None:
    if not task:
        return
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
