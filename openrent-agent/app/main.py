import asyncio
from app.browser.launcher import launch_browser
from app.browser.auth import login

async def main():
    playwright, browser, context, page = await launch_browser()

    try:
        await login(page, context)

        print("System ready for next steps")

    finally:
        await browser.close()
        await playwright.stop()


if __name__ == "__main__":
    asyncio.run(main())