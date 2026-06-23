"""
Central business rules configuration for the AI Advisor.
All capacity estimates and operational decisions reference this file.
"""

RULES = {
    # Messaging capacity
    "messages_per_account_per_day": 8,
    "safe_daily_limit_low": 10,
    "safe_daily_limit_high": 25,
    "high_risk_daily_limit": 35,

    # SIM cards
    "sims_per_account": 1,

    # Proxies
    "max_accounts_per_proxy": 2,

    # Reply rates
    "reply_rate_target_pct": 20,
    "good_reply_rate_pct": 30,

    # Accounts per area type
    "accounts_small_town": 2,
    "accounts_medium_city": 5,
    "accounts_large_city": 10,
    "accounts_london_borough": 3,

    # Weekly new listings per area type (UK OpenRent averages)
    "listings_per_week_small_town": 30,
    "listings_per_week_medium_city": 120,
    "listings_per_week_large_city": 300,
    "listings_per_week_london_borough": 80,

    # Coverage buffer
    "listing_attrition_pct": 25,  # assume 25% of listings are skipped/old
}


def rules_summary_for_prompt() -> str:
    return (
        f"- Each account can send up to {RULES['messages_per_account_per_day']} initial messages per day\n"
        f"- Each account needs its own SIM card (phone number)\n"
        f"- At most {RULES['max_accounts_per_proxy']} accounts should share one connection service (proxy)\n"
        f"- Safe daily message limit: {RULES['safe_daily_limit_low']}–{RULES['safe_daily_limit_high']} per account\n"
        f"- Target reply rate: at least {RULES['reply_rate_target_pct']}%\n"
        f"- Small UK towns: ~{RULES['listings_per_week_small_town']} new rental listings per week\n"
        f"- Medium UK cities (e.g. Leeds, Nottingham): ~{RULES['listings_per_week_medium_city']} per week\n"
        f"- Large UK cities (e.g. Birmingham, Sheffield): ~{RULES['listings_per_week_large_city']} per week\n"
        f"- London boroughs: ~{RULES['listings_per_week_london_borough']} per week each\n"
        f"- Recommended accounts for a small town: {RULES['accounts_small_town']}\n"
        f"- Recommended accounts for a medium city: {RULES['accounts_medium_city']}\n"
        f"- Recommended accounts for a large city: {RULES['accounts_large_city']}\n"
        f"- Recommended accounts per London borough: {RULES['accounts_london_borough']}\n"
        f"- Allow ~{RULES['listing_attrition_pct']}% extra capacity for skipped/old listings\n"
    )
