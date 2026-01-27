import asyncio
from ai_reply import generate_reply
from playwright.async_api import async_playwright
from db import close_with_phone, conversation_exists, insert_conversation,  is_closed, mark_replied
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

# ---------------- SEND ONE MESSAGE ---------------------

async def send_one_message(page):
    await page.goto("https://www.openrent.co.uk/")
    await page.get_by_text("Featured Properties").scroll_into_view_if_needed()

    await page.wait_for_selector(".swiper-slide a.stretched-link", state="attached")

    cards = await page.query_selector_all(".swiper-slide:not(:has(.badge)) a.stretched-link")
    print("Available cards:", len(cards))

    for card in cards:
        property_url = await card.get_attribute("href")

        await card.scroll_into_view_if_needed()
        await card.click(force=True)
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

# ---------------- READ REPLIES FROM LIST ----------------

# async def process_threads(page):
#     print("\nScanning threads...\n")

#     await page.goto("https://www.openrent.co.uk/myenquiries")
#     await page.wait_for_selector("div[id^='thread-']", state="attached")

#     threads = await page.query_selector_all("div[id^='thread-']")
#     print(f"Found {len(threads)} threads\n")

#     for thread in thread_ids:
#         thread_id = (await thread.get_attribute("id")).replace("thread-", "")

#         insert_conversation(thread_id, None)
#         if is_closed(thread_id):
#             continue

#         sender_el = await thread.query_selector("div[id^='last-message-container'] p.mb-0")
#         sender_text = await sender_el.inner_text() if sender_el else ""

#         # Skip if last sender is YOU
#         if sender_text.startswith("You:"):
#             continue

#         print("Processing thread:", thread_id)

#         view_btn = await thread.query_selector("a:has-text('View messages')")
#         await view_btn.click()
#         await page.wait_for_load_state("networkidle")

#         full_text = await read_full_conversation(page)
#         print("Full conversation text:", full_text)

#         phone = extract_phone(full_text)

#         if phone:
#             print("📞 Phone found:", phone)
#             close_with_phone(thread_id, phone)
#             await page.go_back()
#             continue

#         print("No phone found. Generating AI reply...")

#         ai_reply = generate_reply(full_text)

#         print("AI Reply:", ai_reply)

#         await page.get_by_role("textbox").fill(ai_reply)
#         await page.get_by_role("button", name="Send").click()
#         mark_replied(thread_id)

#         await page.wait_for_timeout(1500)
#         await page.go_back()
async def process_threads(page):
    print("\nScanning threads...\n")

    await page.goto("https://www.openrent.co.uk/myenquiries")
    await page.wait_for_selector("div[id^='thread-']", state="attached")

    # Get all thread IDs first (avoids stale element issues)
    thread_ids = await page.eval_on_selector_all(
        "div[id^='thread-']",
        "els => els.map(e => e.id.replace('thread-', ''))"
    )

    print(f"Found {len(thread_ids)} threads\n")

    for thread_id in thread_ids:
        try:
            thread_selector = f"#thread-{thread_id}"
            thread = page.locator(thread_selector)

            # Insert if not exists
            insert_conversation(thread_id, None)

            if is_closed(thread_id):
                print("Already closed:", thread_id)
                continue

            sender_el = thread.locator("p.mb-0").first
            sender_text = (await sender_el.inner_text()).strip() if await sender_el.count() else ""

            # Skip if last sender is YOU
            if sender_text.startswith("You:"):
                print("Skipping (last sender YOU):", thread_id)
                continue

            print("Processing thread:", thread_id)

            view_btn = thread.locator("a:has-text('View messages')")
            await view_btn.click()
            await page.wait_for_load_state("networkidle")

            full_text = await read_full_conversation(page)
            print("Full conversation text:\n", full_text)

            phone = extract_phone(full_text)

            if phone:
                print("📞 Phone found:", phone)
                close_with_phone(thread_id, phone)
                await page.goto("https://www.openrent.co.uk/myenquiries")
                await page.wait_for_selector("div[id^='thread-']", state="attached")
                continue

            print("No phone found. Generating AI reply...")

            ai_reply = generate_reply(full_text)
            print("AI Reply:\n", ai_reply)

            await page.get_by_role("textbox").fill(ai_reply)
            await page.get_by_role("button", name="Send").click()
            mark_replied(thread_id)

            await page.wait_for_timeout(1500)

            # Go back safely
            await page.goto("https://www.openrent.co.uk/myenquiries")
            await page.wait_for_selector("div[id^='thread-']", state="attached")

        except Exception as e:
            print(f"⚠️ Error processing {thread_id}: {e}")
            await page.goto("https://www.openrent.co.uk/myenquiries")
            await page.wait_for_selector("div[id^='thread-']", state="attached")
            continue

async def read_full_conversation(page):
    await page.wait_for_selector(".message-content")

    messages = await page.query_selector_all(".message-content")
    full_text = []

    for msg in messages:
        text = await msg.inner_text()
        full_text.append(text.strip())

    return "\n".join(full_text)

# ---------------- MAIN ----------------

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=700)
        page = await browser.new_page()

        await login(page)
        # await send_one_message(page)
        # await read_replies_from_list(page)
        await process_threads(page)

        print("\nRun complete.")
        await browser.close()

asyncio.run(main())
# ---------------- MAIN ----------------