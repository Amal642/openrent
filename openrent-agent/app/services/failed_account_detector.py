import asyncio
from contextlib import suppress

from app.utils.logger import logger

DETECTOR_INTERVAL_SECONDS = 3600  # run once per hour


async def _run_detector_cycle():
    from app.db.repository import detect_and_mark_failed_accounts

    await asyncio.to_thread(detect_and_mark_failed_accounts)
    logger.info("Failed account detection cycle complete")


async def failed_account_detector_loop():
    while True:
        try:
            await _run_detector_cycle()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception(f"Failed account detector cycle error: {exc}")
        await asyncio.sleep(DETECTOR_INTERVAL_SECONDS)


def start_failed_account_detector():
    return asyncio.create_task(failed_account_detector_loop(), name="failed-account-detector")


async def stop_failed_account_detector(task):
    if not task:
        return
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
