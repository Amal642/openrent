
from app.openrent.search import get_account_search_urls
from app.openrent.listings import scrape_search_results
from app.db.repository import mark_scraped_today
from app.utils.logger import logger


async def scrape_account_listings(account, page):
    """
    Fetch all search profile URLs for the account,
    scrape OpenRent for new listings, and persist them to DB.
    Runs once per calendar day per account (gated by has_scraped_today).
    """
    logger.info("=" * 60)
    logger.info("STARTING LISTING DISCOVERY")
    logger.info(f"ACCOUNT: {account.email} (id={account.id})")

    # ── Load search profiles ───────────────────────────────────
    logger.info("LOADING SEARCH PROFILES")
    search_urls = get_account_search_urls(account.id)

    if not search_urls:
        logger.warning(
            f"NO ACTIVE SEARCH PROFILES for account {account.id} "
            f"({account.email}) — skipping scrape. "
            "Create a search profile in the dashboard first."
        )
        mark_scraped_today(account.id)
        return

    logger.info(f"FOUND {len(search_urls)} SEARCH PROFILE(S)")
    for item in search_urls:
        logger.info(
            f"  profile_id={item['profile_id']} → {item['url']}"
        )

    # ── Scrape each profile URL ────────────────────────────────
    for item in search_urls:
        logger.info(
            f"SCRAPING PROFILE {item['profile_id']}: {item['url']}"
        )
        try:
            await scrape_search_results(
                page,
                item["profile_id"],
                item["url"],
            )
        except Exception as exc:
            logger.exception(
                f"SCRAPING FAILED for profile {item['profile_id']} "
                f"(account {account.id}): {exc}"
            )

    mark_scraped_today(account.id)
    logger.info(f"LISTING DISCOVERY COMPLETE for account {account.email}")
    logger.info("=" * 60)
