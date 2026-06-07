
from app.openrent.search import get_account_search_urls
from app.openrent.listings import scrape_search_results
from app.db.repository import mark_scraped_today
from app.utils.logger import logger


async def scrape_account_listings(account, page, new_limit: int = 25) -> int:
    """
    Fetch search profile URLs for the account and scrape OpenRent for new listings.
    Returns total new listings discovered across all profiles.
    Caps each profile at new_limit new listings.
    """
    search_urls = get_account_search_urls(account.id)

    if not search_urls:
        logger.warning(
            f"DISCOVERY_NO_PROFILES account_id={account.id} email={account.email}"
        )
        return 0

    logger.info(
        f"DISCOVERY_STARTED account_id={account.id} profiles={len(search_urls)}"
    )

    total_new = 0
    for item in search_urls:
        try:
            new = await scrape_search_results(
                page,
                item["profile_id"],
                item["url"],
                new_limit=new_limit,
            )
            total_new += new
        except Exception as exc:
            logger.exception(
                f"DISCOVERY_PROFILE_FAILED profile_id={item['profile_id']} "
                f"account_id={account.id} error={exc}"
            )

    mark_scraped_today(account.id)
    logger.info(
        f"DISCOVERY_COMPLETE account_id={account.id} new_listings={total_new}"
    )
    return total_new
