import asyncio
from contextlib import suppress
from datetime import datetime, timedelta

from app.config import settings
from app.db.repository import (
    claim_due_sheet_exports,
    mark_sheet_export_failed,
)
from app.utils.logger import logger


async def _run_dispatch_cycle():
    if not settings.GOOGLE_SHEETS_ENABLED:
        return 0

    export_ids = await asyncio.to_thread(
        claim_due_sheet_exports,
        20,
        15,
        settings.GOOGLE_SHEETS_MAX_ATTEMPTS,
    )
    if not export_ids:
        return 0

    from app.jobs.sync_google_sheets import run_lead_sheet_export_sync
    from app.queue.queues import integration_queue

    queued = 0
    for export_id in export_ids:
        try:
            job = integration_queue.enqueue(
                run_lead_sheet_export_sync,
                export_id,
                job_timeout="5m",
            )
            queued += 1
            logger.info(
                "GOOGLE_SHEETS_EXPORT_QUEUED "
                f"export_id={export_id} job_id={job.id} queue=integrations"
            )
        except Exception as exc:
            next_attempt_at = datetime.utcnow() + timedelta(minutes=1)
            mark_sheet_export_failed(
                export_id,
                error=f"Queueing failed: {exc}",
                next_attempt_at=next_attempt_at,
                permanent=False,
            )
            logger.exception(
                "GOOGLE_SHEETS_EXPORT_QUEUE_FAILED "
                f"export_id={export_id} next_attempt_at={next_attempt_at}"
            )

    logger.info(
        "GOOGLE_SHEETS_DISPATCH_CYCLE "
        f"claimed={len(export_ids)} queued={queued}"
    )
    return queued


async def google_sheets_export_dispatcher_loop():
    while True:
        try:
            await _run_dispatch_cycle()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception(
                f"GOOGLE_SHEETS_DISPATCH_CYCLE_FAILED error={exc}"
            )
        await asyncio.sleep(settings.GOOGLE_SHEETS_DISPATCH_SECONDS)


def start_google_sheets_export_dispatcher():
    if not settings.GOOGLE_SHEETS_ENABLED:
        logger.info("GOOGLE_SHEETS_DISPATCHER_DISABLED")
        return None
    logger.info(
        "GOOGLE_SHEETS_DISPATCHER_STARTED "
        f"interval_seconds={settings.GOOGLE_SHEETS_DISPATCH_SECONDS}"
    )
    return asyncio.create_task(
        google_sheets_export_dispatcher_loop(),
        name="google-sheets-export-dispatcher",
    )


async def stop_google_sheets_export_dispatcher(task):
    if not task:
        return
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
