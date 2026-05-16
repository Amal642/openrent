import random
import re

from datetime import (
    datetime,
    timedelta
)

AVAILABILITY_OPTIONS = [
    "Available after 5pm most weekdays.",
    "Flexible this week including weekends.",
    "Usually free evenings after work.",
    "Can do evenings or weekends.",
    "Available most days this week."
]

async def open_listing(page, listing):

    print(f"\nOpening listing: {listing.property_url}")

    await page.goto(listing.property_url)

    await page.wait_for_load_state("networkidle")

async def extract_listing_metadata(page):

    content = await page.content()

    # ---------------- RENT ----------------

    rent_match = re.search(
        r"Rent PCM.*?£([\d,]+)",
        content,
        re.DOTALL
    )

    rent_pcm = None

    if rent_match:

        rent_pcm = int(
            rent_match.group(1)
            .replace(",", "")
        )

    # ---------------- AVAILABLE FROM ----------------

    available_match = re.search(
        r"Available From.*?<td>(.*?)</td>",
        content,
        re.DOTALL
    )

    available_from_raw = None

    if available_match:

        available_from_raw = (
            available_match.group(1)
            .strip()
        )

    if (
        not available_from_raw
        or
        available_from_raw.lower() == "today"
    ):

        available_from = datetime.utcnow()

    else:

        try:

            available_from = datetime.strptime(
                available_from_raw,
                "%d %B %Y"
            )

        except:

            available_from = datetime.utcnow()

    # ---------------- BEDROOMS ----------------

    bedrooms = 1

    room_match = re.search(
        r"Max Tenants:</span>\s*(\d+)",
        content
    )

    if room_match:

        bedrooms = int(
            room_match.group(1)
        )

    else:

        bed_match = re.search(
            r"(\d+)\s*Bed",
            content,
            re.IGNORECASE
        )

        if bed_match:

            bedrooms = int(
                bed_match.group(1)
            )

    return {
        "rent_pcm": rent_pcm,
        "available_from": available_from,
        "bedrooms": bedrooms
    }

async def detect_form_type(page):

    screening_dropdown = await page.query_selector(
        "#ScreeningInfo_FurnishedStateRequired"
    )

    if screening_dropdown:
        return 2

    return 1

async def fill_screening_form(
    page,
    metadata
):

    # ---------------- QUESTIONS ----------------

    await page.check(
        'input[name="ScreeningInfo.IsStudent"][value="false"]'
    )

    await page.check(
        'input[name="ScreeningInfo.OnBenefits"][value="false"]'
    )

    await page.check(
        'input[name="ScreeningInfo.HasPets"][value="false"]'
    )

    await page.check(
        'input[name="ScreeningInfo.IsSmoker"][value="false"]'
    )

    await page.check(
        'input[name="ScreeningInfo.HasRightToRent"][value="true"]'
    )

    # ---------------- FURNISHING ----------------

    await page.select_option(
        "#ScreeningInfo_FurnishedStateRequired",
        value="2"
    )

    # ---------------- MOVE IN DATE ----------------

    move_in_date = (
        metadata["available_from"]
        +
        timedelta(days=14)
    )

    formatted_date = move_in_date.strftime(
        "%d %B %Y"
    )

    await page.fill(
        "#ScreeningInfo_MustMoveInBy",
        formatted_date
    )

    # ---------------- INCOME ----------------

    rent = metadata["rent_pcm"] or 1000

    income = (
        rent * 30
    ) + 20000

    await page.fill(
        "#ScreeningInfo_CombinedMonthlyIncome",
        str(income)
    )

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
    message_text,
    metadata
):

    print(f"\nOpening message page: {message_url}")

    await page.goto(message_url)

    await page.wait_for_load_state(
        "networkidle"
    )

    form_type = await detect_form_type(
        page
    )

    print(
        f"Detected form type: {form_type}"
    )

    # ---------------- TYPE 2 ----------------

    if form_type == 2:

        await fill_screening_form(
            page,
            metadata
        )

    # ---------------- AVAILABILITY ----------------

    availability_text = random.choice(
        AVAILABILITY_OPTIONS
    )

    availability_input = await page.query_selector(
        "#Availability"
    )

    if not availability_input:

        availability_input = await page.query_selector(
            'input[name="Availability"]'
        )

    if availability_input:

        await availability_input.fill(
            availability_text
        )

    # ---------------- MESSAGE ----------------

    textarea = await page.query_selector(
        "textarea"
    )

    if not textarea:

        textarea = await page.query_selector(
            "textarea"
        )

        if not textarea:
            raise Exception(
                "Message textarea not found"
            )

    # await textarea.fill(
    #     message_text
    # )
    await safe_fill(
        textarea,
        message_text
    )
    print("Message inserted")

    # ---------------- CHECKBOX ----------------

    checkbox = await page.query_selector(
        'input[type="checkbox"]'
    )

    if not checkbox:

        checkbox = await page.query_selector(
            'input[type="checkbox"]'
        )

    if checkbox:

        await checkbox.check()

    # ---------------- SUBMIT ----------------

    buttons = await page.query_selector_all(
        "button[type='submit']"
    )

    submit_button = None

    for button in buttons:

        try:

            text = await button.inner_text()

            text = text.strip().lower()

            print(
                "Found submit candidate:",
                text
            )

            if "request viewing" in text:

                submit_button = button
                break

        except:
            continue

    if not submit_button:

        raise Exception(
            "Correct submit button not found"
        )

    await submit_button.click()

    print("Clicked submit button")

    await page.wait_for_load_state(
        "networkidle"
    )

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

async def safe_fill(
    locator,
    value,
    retries=3
):

    for attempt in range(retries):

        try:

            await locator.fill(value)

            return True

        except Exception:

            if attempt == retries - 1:
                raise

            await locator.page.wait_for_timeout(
                1000
            )

    return False
