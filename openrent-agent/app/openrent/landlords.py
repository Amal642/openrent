import re

from app.utils.human import (
    random_sleep
)

from app.utils.logger import (
    logger
)


async def extract_landlord_id(page):

    landlord_link = await page.query_selector(
        'a[href*="/account/view/"]'
    )

    if not landlord_link:

        return None

    href = await landlord_link.get_attribute(
        "href"
    )

    if not href:

        return None

    match = re.search(
        r"/account/view/(\d+)",
        href
    )

    if not match:

        return None

    return match.group(1)


async def get_landlord_property_count(
    page,
    landlord_id
):

    url = (
        "https://www.openrent.co.uk/"
        f"search/searchbylandlord"
        f"?landlordID={landlord_id}"
    )

    logger.info(
        f"Checking landlord properties: "
        f"{landlord_id}"
    )

    await random_sleep(2, 5)

    await page.goto(url)

    await random_sleep(3, 6)

    links = await page.query_selector_all(
        'a[href^="/property-to-rent/"]'
    )

    property_ids = set()

    for link in links:

        href = await link.get_attribute(
            "href"
        )

        if not href:
            continue

        property_ids.add(href)

    count = len(property_ids)

    logger.info(
        f"Landlord {landlord_id} "
        f"has {count} properties"
    )

    return count


async def landlord_is_agent(
    page,
    threshold=5
):

    landlord_id = await extract_landlord_id(
        page
    )

    if not landlord_id:

        logger.warning(
            "No landlord ID found"
        )

        return False

    count = await get_landlord_property_count(
        page,
        landlord_id
    )

    return count >= threshold