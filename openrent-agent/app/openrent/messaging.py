async def open_listing(page, listing):

    print(f"\nOpening listing: {listing.property_url}")

    await page.goto(listing.property_url)

    await page.wait_for_load_state("networkidle")

async def get_existing_thread_id(page):

    try:

        banner = page.locator(
            "text=You have already enquired about this property"
        )

        if await banner.count() == 0:
            return None

        message_link = page.locator(
            'a[href^="/messages/"]'
        ).first

        href = await message_link.get_attribute("href")

        if not href:
            return None

        return extract_thread_id(href)

    except Exception as e:

        print("Existing thread detection failed:", e)

        return None

async def get_message_link(page):

    links = await page.query_selector_all("a")

    for link in links:

        href = await link.get_attribute("href")

        if not href:
            continue

        if "/messagelandlord/" in href:
            return href

    return None

async def can_contact_landlord(page):

    message_link = await get_message_link(page)

    return message_link is not None
async def send_initial_message(
    page,
    message_url,
    message_text
):

    print(f"\nOpening message page: {message_url}")

    await page.goto(message_url)

    await page.wait_for_load_state("networkidle")

    # Find textarea
    textarea = await page.query_selector("textarea")

    if not textarea:
        raise Exception("Message textarea not found")

    # Fill message
    await textarea.fill(message_text)

    print("Message inserted")

    # Find submit button
    buttons = await page.query_selector_all(
    "button[type='submit']"
    )

    submit_button = None

    for button in buttons:

        try:
            text = await button.inner_text()

            text = text.strip().lower()

            print("Found submit candidate:", text)

            if "request viewing" in text:
                submit_button = button
                break

        except:
            continue

    if not submit_button:
        raise Exception("Correct submit button not found")

    if not submit_button:
        raise Exception("Submit button not found")

    button_text = await submit_button.inner_text()

    print(f"Found submit button: {button_text}")

    # Click button
    await submit_button.click()

    print("Clicked submit button")

    await page.wait_for_load_state("networkidle")

    final_url = page.url

    print("Final URL:", final_url)

    return final_url

def extract_thread_id(url):

    parts = url.strip("/").split("/")

    if not parts:
        return None

    last_part = parts[-1]

    if last_part.isdigit():
        return last_part

    return None
