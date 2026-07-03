import asyncio
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.alerts.bot import run_alert_bot
from app.db.init_db import init_db


async def main():
    init_db()
    await run_alert_bot()


if __name__ == "__main__":
    asyncio.run(main())
