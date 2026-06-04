import asyncio
from datetime import datetime

from app.db.repository import (
    get_active_accounts,
    is_account_on_cooldown,
    set_account_cooldown,
)
from app.db.init_db import init_db
from app.workers.account_worker import run_account_worker
from app.utils.logger import logger
from app.utils.scheduling import is_operating_hours
from app.config import settings


def _select_accounts_for_tick(accounts):
    """
    Return the subset of accounts to run this tick:

    * One account per proxy (proxy_id) — prevents two accounts sharing the
      same proxy from running simultaneously.
    * Accounts without a proxy are included up to a cap of 5 per tick to
      avoid overloading the server IP.
    * Accounts currently on cooldown are excluded before this function is
      called (caller already filtered them out).
    """
    selected = []
    seen_proxy_ids: set = set()
    no_proxy_count = 0

    for account in accounts:
        if account.proxy_id:
            if account.proxy_id not in seen_proxy_ids:
                seen_proxy_ids.add(account.proxy_id)
                selected.append(account)
        else:
            if no_proxy_count < 5:
                selected.append(account)
                no_proxy_count += 1

    return selected


async def run_once():
    # ── Business-hours gate ───────────────────────────────────
    if not is_operating_hours():
        logger.info("Outside operating hours (08:15–22:00 UK). Scheduler sleeping.")
        return

    # ── Account eligibility ───────────────────────────────────
    accounts = get_active_accounts()
    if not accounts:
        logger.warning("No active accounts")
        return

    eligible = [a for a in accounts if not is_account_on_cooldown(a.id)]

    if not eligible:
        logger.info("All accounts are on cooldown. Skipping tick.")
        return

    # ── Proxy-aware batch selection ───────────────────────────
    selected = _select_accounts_for_tick(eligible)

    logger.info(
        f"Tick: {len(eligible)} eligible, {len(selected)} selected "
        f"(proxy-aware batch), {len(accounts) - len(eligible)} on cooldown"
    )

    # ── Run selected accounts in parallel ─────────────────────
    tasks = [run_account_worker(account) for account in selected]
    await asyncio.gather(*tasks)

    # ── Apply post-run cooldowns ──────────────────────────────
    for account in selected:
        set_account_cooldown(account.id)

    logger.info(f"Worker tick completed at {datetime.utcnow().isoformat()}")


async def main():
    init_db()
    while True:
        await run_once()
        await asyncio.sleep(settings.WORKER_TICK_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
