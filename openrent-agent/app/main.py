import asyncio
from playwright.async_api import async_playwright

from app.browser.auth import login
from app.config import EMAIL, PASSWORD

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=500)
        page = await browser.new_page()

        await login(page, EMAIL, PASSWORD)

        print("Login successful")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())