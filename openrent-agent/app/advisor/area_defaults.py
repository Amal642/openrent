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
# NOTE: this static dict is now only the SEED for the area_configs table.
# Runtime consumers must read areas via get_area_defaults() (DB-backed and
# editable from the Area Intelligence dashboard), not import AREA_DEFAULTS
# directly. On first run init_db seeds area_configs from this dict.
for _config in AREA_DEFAULTS.values():
    _config.setdefault("region", "South")


def get_area_defaults() -> dict[str, dict]:
    """Return the live area config dict, keyed by location.

    Reads active rows from the area_configs table so areas added/removed from
    the dashboard take effect without a redeploy. Falls back to the static
    AREA_DEFAULTS seed if the DB is unavailable (e.g. very early startup) so
    the system degrades to today's behavior rather than an empty area list.
    """
    try:
        from app.db.repository import get_area_configs

        rows = get_area_configs(active_only=True)
    except Exception:
        return {loc: dict(cfg) for loc, cfg in AREA_DEFAULTS.items()}

    if not rows:
        return {loc: dict(cfg) for loc, cfg in AREA_DEFAULTS.items()}

    result: dict[str, dict] = {}
    for row in rows:
        result[row["location"]] = {
            "price_min": row["price_min"],
            "price_max": row["price_max"],
            "bedrooms_min": row["bedrooms_min"],
            "bedrooms_max": row["bedrooms_max"],
            "area": row["area"],
            "region": row.get("region") or "South",
        }
    return result
