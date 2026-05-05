import asyncio
from playwright.async_api import async_playwright
from db import property_already_messaged, insert_conversation, get_summary_counts

def extract_property_id(url):
    return url.rstrip("/").split("/")[-1]

async def login(page):
    await page.goto("https://www.openrent.co.uk/")
    await page.wait_for_load_state("networkidle")

async def send_one_message(page):
    await page.goto("https://www.openrent.co.uk/")
    await page.wait_for_selector(".swiper-slide", state="attached")

    cards = await page.query_selector_all(".swiper-slide:not(:has(.badge)) a.stretched-link")

    for card in cards:
        href = await card.get_attribute("href")
        full_url = "https://www.openrent.co.uk" + href
        property_id = extract_property_id(href)

        if property_already_messaged(property_id):
            print("Already messaged:", property_id)
            continue

        print("Messaging property:", property_id)

        await page.wait_for_timeout(3000)
        await card.click(force=True)
        await page.wait_for_load_state("networkidle")

        await page.get_by_role("link", name="Message Landlord or Request").click()

        await page.get_by_role("textbox", name="Message").fill(
            "Hi, I’m Mary, I work in IT. My husband and I really like your property and were hoping to have a quick call before booking a viewing.\nCould you please share your phone number?\nThanks so much!"
        )

        await page.wait_for_timeout(2000)
        await page.get_by_role("button", name="Request Viewing").click()
        await page.wait_for_url("**/messages/**", timeout=10000)

        thread_url = page.url
        thread_id = thread_url.split("/")[-1]

        insert_conversation(thread_id, property_id, full_url)
        print("Saved conversation:", thread_id)

        return "SENT"

    return "NONE"

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=800)
        page = await browser.new_page()

        await login(page)
        result = await send_one_message(page)

        await browser.close()

    print("\n===== RUN SUMMARY =====")
    print("Result:", result)
    summary = get_summary_counts()
    for status, count in summary:
        print(f"{status}: {count}")

asyncio.run(main())
