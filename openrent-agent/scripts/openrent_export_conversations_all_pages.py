import asyncio
import re
from playwright.async_api import async_playwright

BASE_URL = "https://www.openrent.co.uk"
OUTPUT_FILE = "conversations.md"

# ---------------------------------------
# CLEANERS
# ---------------------------------------

BAD_PHRASES = [
    "About",
    "Pricing & Services",
    "Manage",
    "Add Listing",
    "Need Help?",
    "Verified Tenant",
    "Place Holding Deposit",
    "Complete Referencing",
    "Sign Contract",
    "Pay Final Balance",
    "Tenant Insights",
    "Rent Now Progress",
    "Property available",
    "Property no longer available",
    "Viewing Requested",
    "Availability:",
    "Pre-Screening Answers",
    "Tenant Viewing Availability",
    "Cancel Enquiry",
    "Chase Landlord",
    "Report Listing",
    "View listing",
    "Joined",
    "User Notes",
    "Ready to move forward?",
    "Be first in the landlord's inbox",
]

TIME_PATTERNS = [
    r"^\d+\s+hours?\s+ago$",
    r"^\d+\s+days?\s+ago$",
    r"^\d+\s+weeks?\s+ago$",
    r"^\d+\s+months?\s+ago$",
    r"^Yesterday$",
    r"^Today$",
    r"^Friday$",
    r"^Monday$",
    r"^Tuesday$",
    r"^Wednesday$",
    r"^Thursday$",
    r"^Saturday$",
    r"^Sunday$",
]


def clean_text(text):
    if not text:
        return ""

    text = text.strip()

    # remove timestamps
    for pattern in TIME_PATTERNS:
        if re.match(pattern, text, re.IGNORECASE):
            return ""

    # remove unwanted phrases
    for phrase in BAD_PHRASES:
        if phrase.lower() in text.lower():
            return ""

    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def dedupe_messages(messages):
    cleaned = []
    seen = set()

    for role, msg in messages:
        key = (role, msg.strip())

        if not msg.strip():
            continue

        if key in seen:
            continue

        seen.add(key)
        cleaned.append((role, msg))

    return cleaned


# ---------------------------------------
# EXTRACT CHAT ONLY
# ---------------------------------------

async def extract_messages(page):

    import re

    messages = []

    #
    # ONLY ACTUAL CHAT BUBBLES
    #
    bubbles = await page.query_selector_all(
        "div.message-content"
    )

    for bubble in bubbles:

        try:

            text = await bubble.inner_text()

            if not text:
                continue

            text = text.strip()

            #
            # SKIP EMPTY
            #
            if len(text) < 2:
                continue

            lower_text = text.lower()

            #
            # REMOVE OPENRENT SYSTEM / PROMO MESSAGES
            #
            blocked_phrases = [
                "verified tenant",
                "boosted to the top of their inbox",
                "learn more about verified tenant",
                "chris from openrent here",
                "openrent here!",
                "it's only £10",
                "applies to all your enquiries",
            ]

            should_skip = False

            for phrase in blocked_phrases:

                if phrase in lower_text:
                    should_skip = True
                    break

            if should_skip:
                continue

            #
            # DETERMINE ROLE
            #
            class_name = (
                await bubble.get_attribute("class")
                or ""
            )

            if "current-user" in class_name:
                role = "Tenant"
            else:
                role = "Landlord"

            #
            # CLEAN TEXT
            #
            text = re.sub(
                r"\n{3,}",
                "\n\n",
                text
            )

            text = text.strip()

            #
            # ESCAPE QUOTES
            #
            text = text.replace(
                '"',
                '\\"'
            )

            messages.append(
                (role, text)
            )

        except Exception as e:

            print(
                "Bubble parse error:",
                e
            )

    #
    # REMOVE DUPLICATES
    #
    deduped = []

    seen = set()

    for role, text in messages:

        key = f"{role}:{text}"

        if key in seen:
            continue

        seen.add(key)

        deduped.append(
            (role, text)
        )

    #
    # SKIP LOW QUALITY THREADS
    #
    roles = set()

    for role, _ in deduped:
        roles.add(role)

    #
    # ONLY ONE SIDE TALKING
    #
    if roles == {"Tenant"}:
        return []

    if roles == {"Landlord"}:
        return []

    #
    # REQUIRE REAL CONVERSATION
    #
    if len(deduped) < 2:
        return []

    return deduped
# ---------------------------------------
# GET THREAD LINKS
# ---------------------------------------

async def get_thread_links(page):

    links = set()

    anchors = await page.query_selector_all("a")

    for a in anchors:

        href = await a.get_attribute("href")

        if not href:
            continue

        if "/messages/" in href:

            full = href

            if href.startswith("/"):
                full = BASE_URL + href

            links.add(full)

    return list(links)


# ---------------------------------------
# MAIN
# ---------------------------------------

async def main():

    async with async_playwright() as p:

        browser = await p.chromium.launch(
            headless=False
        )

        page = await browser.new_page()

        #
        # LOGIN
        #
        await page.goto(
            "https://www.openrent.co.uk"
        )

        print("\nLOGIN MANUALLY")
        input("\nPress ENTER after login...")

        all_threads = set()

        #
        # FETCH ALL PAGES
        #
        for start in range(0, 1000, 10):

            url = (
                f"https://www.openrent.co.uk/myenquiries?Start={start}"
            )

            print(f"\nOpening: {url}")

            await page.goto(url)

            await page.wait_for_timeout(3000)

            #
            # stop when page missing
            #
            content = await page.content()

            if "Page:" not in content:
                break

            links = await get_thread_links(page)

            print(f"Found {len(links)} threads")

            if not links:
                break

            all_threads.update(links)

        print(f"\nTOTAL THREADS: {len(all_threads)}")

        #
        # EXPORT
        #
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:

            convo_num = 1

            for thread_url in all_threads:

                try:

                    print(f"\nOpening thread: {thread_url}")

                    await page.goto(thread_url)

                    await page.wait_for_timeout(3000)

                    messages = await extract_messages(page)

                    if not messages:
                        continue

                    f.write(
                        f"## Conversation {convo_num}\n"
                    )

                    f.write(
                        f"Source: {thread_url}\n\n"
                    )

                    for role, text in messages:

                        text = text.replace('"', '\\"')

                        f.write(
                            f'{role}: "{text}"\n\n'
                        )

                    f.write("\n\n")

                    convo_num += 1

                except Exception as e:

                    print("ERROR:", e)

        print("\nDONE")
        print(f"Saved to {OUTPUT_FILE}")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())