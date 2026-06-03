import re

from app.utils.human import (
    random_sleep
)

from app.utils.logger import (
    logger
)


async def extract_property_id(
    property_url
):

    match = re.search(
        r"/(\d+)$",
        property_url
    )

    if not match:
        return None

    return match.group(1)


async def extract_landlord_id(
    page,
    property_url
):

    property_id = await extract_property_id(
        property_url
    )

    if not property_id:

        logger.warning(
            "No property ID found"
        )

        return None

    rent_info_url = (
        "https://www.openrent.co.uk/"
        f"rent/rentnowinfo/{property_id}"
    )

    logger.info(
        f"Opening rent info page: "
        f"{rent_info_url}"
    )

    await random_sleep(2, 5)

    try:
        await page.goto(
            rent_info_url,
            wait_until="domcontentloaded",
            timeout=30_000,
        )
    except Exception:
        logger.warning(
            f"rent info page timeout — continuing with loaded DOM: {rent_info_url}"
        )

    await random_sleep(3, 6)

    landlord_link = await page.query_selector(
        'a[href*="/account/view/"]'
    )

    if not landlord_link:

        logger.warning(
            "No landlord profile link found"
        )

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

        logger.warning(
            "Could not extract landlord ID"
        )

        return None

    landlord_id = match.group(1)

    logger.info(
        f"Landlord ID found: "
        f"{landlord_id}"
    )

    return landlord_id


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

    try:
        await page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=30_000,
        )
    except Exception:
        logger.warning(
            f"Landlord page timeout — continuing with loaded DOM: {url}"
        )

    await random_sleep(3, 6)

    links = await page.query_selector_all(
        'a[href^="/property-to-rent/"]'
    )

    property_links = set()

    for link in links:

        href = await link.get_attribute(
            "href"
        )

        if not href:
            continue

        property_links.add(href)

    count = len(property_links)

    logger.info(
        f"Landlord {landlord_id} "
        f"has {count} properties"
    )

    return count


async def landlord_is_agent(
    page,
    property_url,
    threshold=3
):

    landlord_id = await extract_landlord_id(
        page,
        property_url
    )

    if not landlord_id:

        logger.warning(
            "No landlord ID found; agent status unknown"
        )

        return None

    count = await get_landlord_property_count(
        page,
        landlord_id
    )

    is_agent = count > threshold

    logger.info(
        f"Agent check result: "
        f"{is_agent}"
    )

    return is_agent
