
from app.openrent.search import get_account_search_urls
from app.openrent.listings import scrape_search_results
from app.db.repository import mark_scraped_today
from app.utils.logger import logger


async def scrape_account_listings(account, page):
    """
    Fetch all search profile URLs for the account,
    scrape OpenRent for new listings, and persist them to DB.
    Runs once per calendar day per account.
    """
    search_urls = get_account_search_urls(account.id)

    if not search_urls:
        logger.warning(
            f"No active search profiles found for account {account.id} — skipping scrape"
        )
        mark_scraped_today(account.id)
        return

    for item in search_urls:
        try:
            logger.info(
                f"Scraping profile {item['profile_id']} for account {account.id}: {item['url']}"
            )
            await scrape_search_results(
                page,
                item["profile_id"],
                item["url"],
            )
        except Exception as e:
            logger.exception(
                f"Scraping failed for profile {item['profile_id']} "
                f"(account {account.id}): {e}"
            )

    mark_scraped_today(account.id)
    logger.info(f"Scraping completed for account {account.id}")
