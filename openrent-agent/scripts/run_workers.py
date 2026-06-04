import asyncio

from app.db.repository import (
    get_active_accounts,
    is_account_on_cooldown,
)
from app.db.init_db import init_db
from app.workers.account_worker import run_account_worker
from app.utils.logger import logger
from app.utils.scheduling import is_operating_hours, uk_now
from app.config import settings


IN_FLIGHT_STATUSES = {"running", "queued", "stopping", "retrying"}
HEALTHY_PROXY_STATUSES = {"ok", "healthy"}


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


def _select_accounts_for_tick(accounts):
    """
    Return the subset of accounts to run this tick:

    * One account per proxy (proxy_id) — prevents two accounts sharing the
      same proxy from running simultaneously.
    * Accounts currently on cooldown are excluded before this function is
      called (caller already filtered them out).
    """
    selected = []
    seen_proxy_ids: set = set()

    for account in accounts:
        if account.proxy_id not in seen_proxy_ids:
            seen_proxy_ids.add(account.proxy_id)
            selected.append(account)
        else:
            logger.info(f"Proxy busy, skipping account {account.id}")

    return selected


async def run_once():
    logger.info("Scheduler cycle started")
    current_uk_time = uk_now()
    logger.info(f"Current UK time: {current_uk_time.strftime('%Y-%m-%d %H:%M')}")

    if not is_operating_hours(current_uk_time):
        logger.info("Outside operating hours")
        logger.info("Skipping worker cycle")
        return

    logger.info("Inside operating hours")

    accounts = get_active_accounts()
    if not accounts:
        logger.warning("No active accounts")
        return

    busy_proxy_ids = {
        account.proxy_id
        for account in accounts
        if account.proxy_id
        and str(account.worker_status or "").lower() in IN_FLIGHT_STATUSES
    }

    eligible = []
    for account in accounts:
        status = str(account.worker_status or "").lower()
        if status in IN_FLIGHT_STATUSES:
            continue
        if is_account_on_cooldown(account.id):
            continue
        if not _proxy_is_healthy(account):
            continue
        if account.proxy_id in busy_proxy_ids:
            logger.info(f"Proxy busy, skipping account {account.id}")
            continue
        eligible.append(account)

    logger.info(f"Eligible accounts found: {len(eligible)}")

    if not eligible:
        return

    selected = _select_accounts_for_tick(eligible)
    for account in selected:
        logger.info(f"Queueing account {account.id}")

    tasks = [run_account_worker(account) for account in selected]
    await asyncio.gather(*tasks)

    logger.info("Worker tick completed")


async def main():
    init_db()
    while True:
        await run_once()
        await asyncio.sleep(settings.WORKER_TICK_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
