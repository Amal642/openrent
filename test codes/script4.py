# pip install playwright
# playwright install chromium

import asyncio
from playwright.async_api import async_playwright

async def login(page):
    await page.goto("https://www.openrent.co.uk/")
    await page.get_by_role("link", name="Sign In").click()
    await page.get_by_role("textbox", name="Enter email address").fill("mary.sinclair98@hotmail.com")
    await page.get_by_role("button", name="Continue with email").click()
    await page.get_by_role("textbox", name="Enter password").fill("marysinclair98")
    await page.get_by_role("button", name="Log in").click()

async def sendMsg(page):
    await page.get_by_text("Featured Properties").scroll_into_view_if_needed()

    # Wait until cards exist in the DOM (not visibility-based)
    await page.wait_for_selector(".swiper-slide a.stretched-link", state="attached")
    # filtering out cards with "let agreed" badge
    cards = await page.query_selector_all(".swiper-slide:not(:has(.badge)) a.stretched-link")
    print("Found cards:", len(cards))

    # Scroll second one into view explicitly
    # increment the number after sending once 3,4,5....
    await cards[1].scroll_into_view_if_needed()
    await page.wait_for_timeout(1000)

    await cards[1].click(force=True)
    await page.get_by_role("link", name="Message Landlord or Request").click()
    await page.get_by_role("textbox", name="Message").click()
    await page.get_by_role("textbox", name="Message").fill("Hi, I’m Mary, I work in IT. My husband and I really like your property and were hoping to have a quick call before booking a viewing. \nCould you please share your phone number?\nThanks so much!")
    await page.get_by_role("button", name="Request Viewing").click()
    await page.get_by_role("link", name="OK", exact=True).click()
    await page.get_by_role("button", name="Close").click()



async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False,slow_mo=1000)
        page = await browser.new_page()

        await login(page)
        # wait for 500 __spec__
        await page.wait_for_timeout(500)
        await sendMsg(page)
        await browser.close()

        

asyncio.run(main())
