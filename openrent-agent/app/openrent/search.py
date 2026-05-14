from urllib.parse import urlencode
from app.db.repository import get_search_profiles



BASE_URL = "https://www.openrent.co.uk/properties-to-rent"


def build_search_url(profile):
    """
    Generates dynamic OpenRent search URL
    from SearchProfile object
    """

    location_slug = profile.location.lower().replace(" ", "-")

    params = {
        "term": profile.location,
        "prices_min": profile.price_min,
        "prices_max": profile.price_max,
        "bedrooms_min": profile.bedrooms_min,
        "bedrooms_max": profile.bedrooms_max,
        "area": profile.area
    }

    # Optional filters
    if profile.pets_allowed:
        params["acceptPets"] = "true"

    query_string = urlencode(params)

    return f"{BASE_URL}/{location_slug}?{query_string}"


def get_account_search_urls(account_id):
    """
    Returns all search URLs
    for one account
    """

    profiles = get_search_profiles(account_id)

    results = []

    for profile in profiles:
        url = build_search_url(profile)

        results.append({
            "profile_id": profile.id,
            "url": url
        })

    return results