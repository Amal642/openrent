import asyncio

from app.alerts.bot import run_alert_bot
from app.db.init_db import init_db


async def main():
    init_db()
    await run_alert_bot()


if __name__ == "__main__":
    asyncio.run(main())
