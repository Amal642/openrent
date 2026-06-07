
import re

from app.db.repository import (
    listing_exists,
    create_listing,
)
from app.utils.logger import logger

# Matches OpenRent property URLs:
#   /2884260           (root numeric ID — legacy and most common)
#   /property-to-rent/manchester/2884260  (possible future format)
# We require at least 5 digits so we don't capture /page/2 or similar.
_LISTING_ID_RE = re.compile(r"(?:^|/)(\d{5,})(?:[/?#]|$)")


def _is_bot_page(html: str, title: str) -> str | None:
    """Return a reason string if the page looks like a bot-wall, else None."""
    lower = html.lower()
    if "captcha" in lower or "recaptcha" in lower:
        return "CAPTCHA detected"
    if "sign in" in lower and "password" in lower and "enquir" not in lower:
        return "Login wall detected"
    if "403 forbidden" in title.lower() or "access denied" in title.lower():
        return "403/Access denied"
    if "cloudflare" in lower and "challenge" in lower:
        return "Cloudflare challenge"
    if "just a moment" in title.lower():
        return "Cloudflare JS challenge"
    return None


async def scrape_search_results(
    page,
    search_profile_id,
    search_url,
    new_limit: int = 25,
) -> int:
    """
    Scrape OpenRent search results for a single profile URL.
    Returns the number of new listings saved.
    Stops saving after new_limit new listings to cap memory and bandwidth.
    """
    try:
        await page.goto(search_url, wait_until="domcontentloaded", timeout=30_000)
        await page.wait_for_load_state("networkidle", timeout=20_000)
    except Exception as exc:
        logger.error(f"DISCOVERY_PAGE_LOAD_FAILED profile_id={search_profile_id} error={exc}")
        return 0

    current_url = page.url

    title = await page.title()
    html = await page.content()
    bot_reason = _is_bot_page(html, title)
    if bot_reason:
        logger.error(f"DISCOVERY_BOT_WALL profile_id={search_profile_id} reason={bot_reason}")
        return 0

    if "openrent.co.uk" in current_url and "/properties-to-rent" not in current_url:
        logger.warning(f"DISCOVERY_UNEXPECTED_REDIRECT profile_id={search_profile_id} url={current_url}")

    # Scroll to load lazy-loaded listings — capped at 5 passes to limit memory
    previous_height = 0
    for _ in range(5):
        await page.mouse.wheel(0, 5000)
        await page.wait_for_timeout(2000)
        try:
            current_height = await page.evaluate("document.body.scrollHeight")
        except Exception:
            break
        if current_height == previous_height:
            break
        previous_height = current_height

    # Extract all <a> hrefs that look like OpenRent property links
    all_links = await page.query_selector_all("a")
    candidate_ids: dict[str, str] = {}

    for link in all_links:
        href = await link.get_attribute("href")
        if not href:
            continue

        href = href.strip()

        if not href.startswith("/"):
            continue

        simple_id = href.strip("/")
        if simple_id.isdigit() and len(simple_id) >= 5:
            candidate_ids[simple_id] = f"https://www.openrent.co.uk/{simple_id}"
            continue

        m = _LISTING_ID_RE.search(href)
        if m:
            listing_id = m.group(1)
            if len(listing_id) >= 5 and not any(
                skip in href
                for skip in ["/account/", "/search/", "/page/", "/landlord/"]
            ):
                candidate_ids[listing_id] = (
                    f"https://www.openrent.co.uk/{listing_id}"
                )

    if not candidate_ids:
        logger.warning(f"DISCOVERY_ZERO_CANDIDATES profile_id={search_profile_id} url={current_url}")
        return 0

    new_count = 0

    for listing_id, property_url in candidate_ids.items():
        if new_count >= new_limit:
            break

        if listing_exists(listing_id):
            continue

        try:
            create_listing(
                listing_id=listing_id,
                property_url=property_url,
                search_profile_id=search_profile_id,
            )
            new_count += 1
        except Exception as exc:
            logger.error(f"DISCOVERY_SAVE_FAILED listing_id={listing_id} error={exc}")

    return new_count
