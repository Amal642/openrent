import os
import re
from datetime import datetime

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


async def _save_debug_artifacts(page, tag: str) -> None:
    """Save screenshot + HTML to debug/ folder for post-mortem analysis."""
    try:
        os.makedirs("debug", exist_ok=True)
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        screenshot_path = f"debug/{tag}_{ts}.png"
        html_path = f"debug/{tag}_{ts}.html"

        await page.screenshot(path=screenshot_path, full_page=True)
        html = await page.content()
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html)

        logger.info(f"DEBUG ARTIFACTS: {screenshot_path} | {html_path}")
    except Exception as exc:
        logger.warning(f"Could not save debug artifacts: {exc}")


async def scrape_search_results(
    page,
    search_profile_id,
    search_url,
):
    logger.info("=" * 60)
    logger.info("SCRAPING OPENRENT SEARCH RESULTS")
    logger.info(f"SEARCH URL: {search_url}")
    logger.info(f"SEARCH PROFILE ID: {search_profile_id}")

    # ── Navigate ──────────────────────────────────────────────
    try:
        await page.goto(search_url, timeout=30_000)
        await page.wait_for_load_state("networkidle", timeout=20_000)
    except Exception as exc:
        logger.error(f"PAGE LOAD FAILED: {exc}")
        await _save_debug_artifacts(page, "load_error")
        return

    current_url = page.url
    logger.info(f"CURRENT URL AFTER LOAD: {current_url}")

    # ── Detect bot walls ──────────────────────────────────────
    title = await page.title()
    logger.info(f"PAGE TITLE: {title}")

    html = await page.content()
    bot_reason = _is_bot_page(html, title)
    if bot_reason:
        logger.error(f"BOT WALL DETECTED — {bot_reason}")
        logger.error(f"FIRST 2000 CHARS: {html[:2000]}")
        await _save_debug_artifacts(page, "bot_wall")
        return

    # Redirect to login / home
    if "openrent.co.uk" in current_url and "/properties-to-rent" not in current_url:
        logger.warning(
            f"UNEXPECTED REDIRECT — expected search page, got: {current_url}"
        )
        logger.warning(f"FIRST 1000 CHARS: {html[:1000]}")
        await _save_debug_artifacts(page, "unexpected_redirect")

    # ── Save debug artifacts for every run ────────────────────
    await _save_debug_artifacts(page, "search_results")

    # ── Extract all <a> hrefs ─────────────────────────────────
    all_links = await page.query_selector_all("a")
    logger.info(f"TOTAL <a> TAGS ON PAGE: {len(all_links)}")

    # Collect hrefs that look like OpenRent property links
    candidate_ids: dict[str, str] = {}  # listing_id → property_url

    raw_numeric = 0   # hrefs that match old /NNNNN pattern exactly
    regex_match = 0   # hrefs that match via regex (covers new URL formats)
    skipped_non_slash = 0

    for link in all_links:
        href = await link.get_attribute("href")
        if not href:
            continue

        href = href.strip()

        if not href.startswith("/"):
            skipped_non_slash += 1
            continue

        # Primary: href is exactly /NNNNNN (legacy OpenRent format)
        simple_id = href.strip("/")
        if simple_id.isdigit() and len(simple_id) >= 5:
            raw_numeric += 1
            candidate_ids[simple_id] = f"https://www.openrent.co.uk/{simple_id}"
            continue

        # Secondary: extract trailing numeric segment for future URL formats
        m = _LISTING_ID_RE.search(href)
        if m:
            listing_id = m.group(1)
            # Skip if this looks like a page number (< 5 digits) or
            # known non-listing paths
            if len(listing_id) >= 5 and not any(
                skip in href
                for skip in ["/account/", "/search/", "/page/", "/landlord/"]
            ):
                regex_match += 1
                candidate_ids[listing_id] = (
                    f"https://www.openrent.co.uk/{listing_id}"
                )

    logger.info(
        f"LINK ANALYSIS — total: {len(all_links)} | "
        f"non-slash skipped: {skipped_non_slash} | "
        f"simple-pattern matches: {raw_numeric} | "
        f"regex-pattern matches: {regex_match} | "
        f"unique candidates: {len(candidate_ids)}"
    )

    if not candidate_ids:
        logger.warning(f"ZERO LISTING CANDIDATES FOUND ON PAGE: {current_url}")
        logger.warning(f"PAGE HTML SNIPPET (first 2000 chars):\n{html[:2000]}")
        return

    # ── Save to DB ────────────────────────────────────────────
    logger.info("SAVING LISTINGS TO DATABASE")
    new_count = 0
    skipped_existing = 0

    for listing_id, property_url in candidate_ids.items():
        if listing_exists(listing_id):
            logger.info(f"LISTING ALREADY EXISTS (SKIP): {property_url}")
            skipped_existing += 1
            continue

        try:
            create_listing(
                listing_id=listing_id,
                property_url=property_url,
                search_profile_id=search_profile_id,
            )
            logger.info(f"SAVED LISTING: {property_url}")
            new_count += 1
        except Exception as exc:
            logger.error(f"FAILED TO SAVE LISTING {property_url}: {exc}")

    logger.info(
        f"SCRAPE COMPLETE — new: {new_count} | "
        f"already existed: {skipped_existing} | "
        f"total candidates: {len(candidate_ids)}"
    )
    logger.info("=" * 60)
