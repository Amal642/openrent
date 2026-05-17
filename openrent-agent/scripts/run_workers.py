import asyncio
from datetime import datetime

from app.db.repository import (
    get_active_accounts
)

from app.workers.account_worker import (
    run_account_worker
)

from app.utils.logger import (
    logger
)
from app.config import settings


async def main():
    while True:
        await run_once()
        await asyncio.sleep(settings.WORKER_TICK_SECONDS)


async def run_once():

    accounts = get_active_accounts()

    if not accounts:

        logger.warning(
            "No active accounts"
        )

        return

    logger.info(
        f"Starting {len(accounts)} workers"
    )

    tasks = [

        run_account_worker(account)

        for account in accounts
    ]

    await asyncio.gather(*tasks)

    logger.info(f"Worker tick completed at {datetime.utcnow().isoformat()}")


if __name__ == "__main__":

    asyncio.run(main())
