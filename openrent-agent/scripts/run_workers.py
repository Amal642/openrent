import asyncio

from app.db.repository import (
    get_active_accounts
)

from app.workers.account_worker import (
    run_account_worker
)

from app.utils.logger import (
    logger
)


async def main():

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


if __name__ == "__main__":

    asyncio.run(main())