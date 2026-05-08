from app.db.repository import (
    listing_exists,
    create_listing
)


async def scrape_search_results(
    page,
    search_profile_id,
    search_url
):

    print(f"\nScanning: {search_url}\n")

    await page.goto(search_url)

    await page.wait_for_load_state("networkidle")

    links = await page.query_selector_all("a")

    print(f"Total links found: {len(links)}")

    new_count = 0

    processed = set()

    for link in links:

        href = await link.get_attribute("href")

        if not href:
            continue

        # Match listing URLs like /2884260
        if not href.startswith("/"):
            continue

        listing_id = href.replace("/", "").strip()

        # Only numeric IDs
        if not listing_id.isdigit():
            continue

        # Skip duplicates on same page
        if listing_id in processed:
            continue

        processed.add(listing_id)

        property_url = f"https://www.openrent.co.uk/{listing_id}"

        # DB dedup check
        if listing_exists(listing_id):
            print(f"Skipping existing: {listing_id}")
            continue

        create_listing(
            listing_id=listing_id,
            property_url=property_url,
            search_profile_id=search_profile_id
        )

        print(f"Saved new listing: {listing_id}")

        new_count += 1

    print(f"\nNew listings saved: {new_count}")