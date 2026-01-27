import re
import asyncio
from playwright.async_api import Playwright, async_playwright, expect



async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()
        await page.goto("https://www.openrent.co.uk/")
        await page.get_by_role("link", name="Sign In").click()
        await page.get_by_role("textbox", name="Enter email address").click()
        await page.get_by_role("textbox", name="Enter email address").fill("mary.sinclair98@hotmail.com")
        await page.get_by_role("button", name="Continue with email").click()
        await page.get_by_role("textbox", name="Enter password").click()
        await page.get_by_role("textbox", name="Enter password").fill("marysinclair98")
        await page.get_by_role("button", name="Log in").click()
        await page.get_by_role("link", name="Mary").click()
        await page.get_by_role("link", name="Unread Messages").click()

asyncio.run(run())