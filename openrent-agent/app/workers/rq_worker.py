import asyncio

from app.workers.account_worker import run_account_worker
from app.db.connection import SessionLocal
from app.db.models import Account
from app.db.repository import get_capacity_stats
from app.utils.logger import logger


def run_account_worker_sync(account_id: int):
    stats = get_capacity_stats()
    logger.info(
        f"WORKER_STARTED account_id={account_id} "
        f"ACTIVE_WORKERS={stats['accounts_in_flight']} "
        f"QUEUED_ACCOUNTS={stats['accounts_queued']}"
    )

    db = SessionLocal()
    try:
        account = db.query(Account).filter(
            Account.id == account_id
        ).first()

        if not account:
            raise Exception(f"Account {account_id} not found")

        asyncio.run(run_account_worker(account))

    finally:
        db.close()

    stats = get_capacity_stats()
    logger.info(
        f"WORKER_FINISHED account_id={account_id} "
        f"ACTIVE_WORKERS={stats['accounts_in_flight']} "
        f"QUEUED_ACCOUNTS={stats['accounts_queued']}"
    )
