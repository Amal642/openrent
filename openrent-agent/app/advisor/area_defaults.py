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
for _config in AREA_DEFAULTS.values():
    _config.setdefault("region", "South")
