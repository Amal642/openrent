_BASE = {
    "price_min": 1000,
    "price_max": 4000,
    "bedrooms_min": 0,
    "bedrooms_max": 4,
}

# Per-area search profile defaults for auto-assignment.
# Keyed by the exact location string stored in search_profiles.location.
# Radius (area field) follows existing profiles where available.
# Clapham reduced from 15 to 7 — 15km overlaps heavily with Tooting/Wandsworth/Peckham profiles.
# Croydon reduced from 15 to 10 — 15km from Croydon center extends well beyond South London.
# Woolwich uses 10 — the 15km variant in DB was a duplicate with no clear rationale.
AREA_DEFAULTS: dict[str, dict] = {
    "Bexley, Greater London":                        {**_BASE, "area": 6},
    "Bexleyheath, Greater London":                   {**_BASE, "area": 10},
    "Bromley, Greater London":                       {**_BASE, "area": 5},
    "Clapham, London":                               {**_BASE, "area": 7},
    "Croydon, Greater London":                       {**_BASE, "area": 10},
    "Eltham, London":                                {**_BASE, "area": 5},
    "Green Street Green, Bromley, Greater London":   {**_BASE, "area": 4},
    "Greenwich, London":                             {**_BASE, "area": 5},
    "Hanworth, London":                              {**_BASE, "area": 11},
    "Kingston Upon Thames, Greater London":          {**_BASE, "area": 10},
    "Lewisham, London":                              {**_BASE, "area": 10},
    "Mitcham, London":                               {**_BASE, "area": 5},
    "Peckham, London":                               {**_BASE, "area": 5},
    "Purley, Greater London":                        {**_BASE, "area": 5},
    "Sidcup, Greater London":                        {**_BASE, "area": 10},
    "Sutton, Greater London":                        {**_BASE, "area": 5},
    "Tooting, London":                               {**_BASE, "area": 5},
    "Upper Norwood, London":                         {**_BASE, "area": 11},
    "Wandsworth, London":                            {**_BASE, "area": 5},
    "Woolwich, Greater London":                      {**_BASE, "area": 10},
}

# Every configured area belongs to a region. All existing areas are South
# London; when onboarding North London, add the new areas above with an
# explicit "region": "North" (e.g. "Camden, London": {**_BASE, "area": 5,
# "region": "North"}). Areas without an explicit region default to "South".
#
# NOTE: this static dict is now only the SEED / fallback. Areas live in the
# locations table (region + radius + price defaults + allocatable flag), and
# runtime consumers must read them via get_area_defaults(), not import
# AREA_DEFAULTS directly. On first run init_db seeds allocatable locations from
# this dict.
for _config in AREA_DEFAULTS.values():
    _config.setdefault("region", "South")


def get_area_defaults(allocatable_only: bool = False) -> dict[str, dict]:
    """Return the live area config dict, keyed by location (term_value).

    Areas are derived directly from the locations table: every active location
    is an area for intelligence/metrics purposes. Pass allocatable_only=True to
    restrict to locations flagged for SIM assignment (the allocator's spend
    guardrail). The key is Location.term_value, which is exactly what is stored
    on search_profiles.location — so listings map to areas by construction.

    Falls back to the static AREA_DEFAULTS seed if the DB is unavailable (e.g.
    very early startup) so the system degrades to a known baseline rather than
    an empty area list.
    """
    try:
        from app.db.repository import get_locations

        rows = get_locations(active_only=True, allocatable_only=allocatable_only)
    except Exception:
        return _static_defaults(allocatable_only)

    if not rows:
        return _static_defaults(allocatable_only)

    result: dict[str, dict] = {}
    for row in rows:
        result[row["term_value"]] = {
            "price_min": row["price_min"],
            "price_max": row["price_max"],
            "bedrooms_min": row["bedrooms_min"],
            "bedrooms_max": row["bedrooms_max"],
            "area": row["radius_km"],
            "region": row.get("region") or "South",
        }
    return result


def _static_defaults(allocatable_only: bool) -> dict[str, dict]:
    # The static seed is entirely South London and all-allocatable, so the
    # allocatable_only flag does not filter it further.
    return {loc: dict(cfg) for loc, cfg in AREA_DEFAULTS.items()}
