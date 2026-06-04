import asyncio
from contextlib import suppress

from app.db.repository import (
    get_active_accounts,
    is_account_on_cooldown,
)
from app.utils.logger import logger
from app.utils.scheduling import is_operating_hours, uk_now


SCHEDULER_INTERVAL_SECONDS = 60
IN_FLIGHT_STATUSES = {"running", "queued", "stopping", "retrying"}
HEALTHY_PROXY_STATUSES = {"ok", "healthy"}


def _worker_status(account) -> str:
    return str(getattr(account, "worker_status", "") or "").lower()


def _proxy_is_healthy(account) -> bool:
    proxy = getattr(account, "proxy", None)
    if not proxy or not proxy.is_active:
        return False

    proxy_status = str(getattr(account, "proxy_status", "") or "").lower()
    health_status = str(getattr(proxy, "health_status", "") or "").lower()
    return (
        proxy_status in HEALTHY_PROXY_STATUSES
        or health_status in HEALTHY_PROXY_STATUSES
    )


def _is_eligible(account) -> bool:
    if _worker_status(account) in IN_FLIGHT_STATUSES:
        return False
    if is_account_on_cooldown(account.id):
        return False
    return _proxy_is_healthy(account)


def _select_accounts(accounts):
    selected = []
    busy_proxy_ids = {
        account.proxy_id
        for account in accounts
        if account.proxy_id and _worker_status(account) in IN_FLIGHT_STATUSES
    }
    selected_proxy_ids = set()

    for account in accounts:
        if not _is_eligible(account):
            continue

        if account.proxy_id in busy_proxy_ids or account.proxy_id in selected_proxy_ids:
            logger.info("Proxy busy")
            logger.info(f"Proxy busy. Skipping account {account.id}.")
            continue

        selected.append(account)
        selected_proxy_ids.add(account.proxy_id)

    return selected


async def run_scheduler_cycle():
    logger.info("Scheduler cycle started")
    current_uk_time = uk_now()
    logger.info(f"Current UK time: {current_uk_time.strftime('%Y-%m-%d %H:%M')}")

    if not is_operating_hours(current_uk_time):
        logger.info("Outside operating hours")
        logger.info("Outside operating hours. Skipping scheduler cycle.")
        return

    accounts = get_active_accounts()
    selected = _select_accounts(accounts)
    logger.info(f"Eligible accounts found: {len(selected)}")

    for account in selected:
        logger.info(f"Queueing account {account.id}")
        from app.workers.account_worker import start_account_worker

        result = await start_account_worker(account.id)
        if not result.get("queued"):
            logger.info(
                f"Scheduler skipped account {account.id}: "
                f"{result.get('reason') or 'not_queued'}"
            )


async def scheduler_loop():
    while True:
        try:
            await run_scheduler_cycle()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception(f"Scheduler cycle failed: {exc}")

        await asyncio.sleep(SCHEDULER_INTERVAL_SECONDS)


def start_account_scheduler():
    return asyncio.create_task(scheduler_loop(), name="account-scheduler")


async def stop_account_scheduler(task):
    if not task:
        return
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
