import asyncio

from app.workers.account_worker import run_account_worker
from app.db.connection import SessionLocal
from app.db.models import Account


def run_account_worker_sync(account_id: int):
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
