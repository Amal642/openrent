async def open_listing(page, listing):

    print(f"\nOpening listing: {listing.property_url}")

    await page.goto(listing.property_url)

    await page.wait_for_load_state("networkidle")


async def can_contact_landlord(page):

    links = await page.query_selector_all("a")

    for link in links:

        href = await link.get_attribute("href")

        if not href:
            continue

        if "/messagelandlord/" in href:
            return True

    return False