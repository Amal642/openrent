import asyncio
from playwright.async_api import async_playwright
from db import conversation_exists, get_conversation, insert_conversation, insert_with_phone, update_phone_and_status
from phone import extract_phone

MESSAGE_TEXT = """Hi, I’m Mary, I work in IT. My husband and I really like your property and were hoping to have a quick call before booking a viewing.
Could you please share your phone number?
Thanks so much!"""

EMAIL = "mary.sinclair98@hotmail.com"
PASSWORD = "marysinclair98"

# ---------------- LOGIN ----------------

async def login(page):
    await page.goto("https://www.openrent.co.uk/")
    # YOUR LOGIN CODE GOES HERE
    await page.get_by_role("link", name="Sign In").click()
    await page.get_by_role("textbox", name="Enter email address").fill(EMAIL)
    await page.get_by_role("button", name="Continue with email").click()
    await page.get_by_role("textbox", name="Enter password").fill(PASSWORD)
    await page.get_by_role("button", name="Log in").click()
    await page.wait_for_timeout(2000)

# ---------------- SEND ONE MESSAGE ----------------

async def send_one_message(page):
    await page.goto("https://www.openrent.co.uk/")
    await page.get_by_text("Featured Properties").scroll_into_view_if_needed()

    await page.wait_for_selector(".swiper-slide a.stretched-link", state="attached")

    cards = await page.query_selector_all(".swiper-slide:not(:has(.badge)) a.stretched-link")
    print("Available cards:", len(cards))


# change this code temporarily to cards[1]
    for card in cards:
        property_url = await cards[1].get_attribute("href")

        await cards[1].scroll_into_view_if_needed()
        await cards[1].click(force=True)
        await page.wait_for_load_state("networkidle")

        if await page.locator("text=Message Landlord").count() == 0:
            await page.go_back()
            continue

        await page.get_by_role("link", name="Message Landlord or Request").click()

        thread_url = page.url
        thread_id = thread_url.split("/")[-1]

        if conversation_exists(thread_id):
            print("Already contacted:", thread_id)
            await page.go_back()
            continue

        await page.get_by_role("textbox", name="Message").fill(MESSAGE_TEXT)
        await page.get_by_role("button", name="Request Viewing").click()
        await page.wait_for_timeout(1500)

        insert_conversation(thread_id, property_url)
        print("Message sent to:", thread_id)
        return  # ONLY ONE PER RUN

    print("No new properties found.")

async def read_replies_from_list(page):
    print("\nReading replies from enquiries list...\n")

    await page.goto("https://www.openrent.co.uk/myenquiries")
    await page.wait_for_selector("div[id^='thread-']", state="attached")

    threads = await page.query_selector_all("div[id^='thread-']")
    print(f"Found {len(threads)} threads.\n")

    for thread in threads:
        await page.wait_for_load_state("networkidle")
        thread_url = page.url
        thread_id = thread_url.split("/")[-1]
        # thread_id = await thread.get_attribute("id")
        # thread_id = thread_id.replace("thread-", "")

        last_message = await thread.query_selector("div[id^='last-message-container'] p")
        sender_line = await thread.query_selector("div[id^='last-message-container'] p.mb-0")

        message_text = await last_message.inner_text() if last_message else ""
        sender_text = await sender_line.inner_text() if sender_line else ""

        phone = extract_phone(message_text)
        if sender_text.startswith("You:"):
            continue

        print("Thread:", thread_id)
        print("Sender:", sender_text)
        print("Message:", message_text)

        if phone:
            print("📞 Phone Found:", phone)

            existing = get_conversation(thread_id)
            if existing:
                if existing.get("phone_number") != phone:
                    update_phone_and_status(thread_id, phone)
                    print("Updated existing DB row.")
                else:
                    print("Already stored.")
            else:
                insert_with_phone(thread_id, phone)
                print("Inserted new DB row.")

        # if phone:
        #     print("📞 Phone Found:", phone)
        #     update_phone_and_status(thread_id, phone)

        print("-" * 50)

# ---------------- MAIN ----------------

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, slow_mo=700)
        page = await browser.new_page()

        await login(page)
        # await send_one_message(page)
        await read_replies_from_list(page)

        print("\nRun complete.")
        await browser.close()

asyncio.run(main())
# ---------------- MAIN ----------------