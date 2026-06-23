"""
Deterministic area intelligence for advisor recommendations.

This module reads existing listings, search profiles, accounts, landlords, and
conversation outcomes. It does not call an LLM.
"""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta

from sqlalchemy.orm import joinedload

from app.advisor.rules import RULES
from app.db.connection import SessionLocal
from app.db.models import Account, Conversation, Landlord, Listing, SearchProfile


MIN_CONTACTED_FOR_RATE = 5
MIN_TOTAL_LISTINGS_FOR_DECISION = 10


@dataclass
class AreaMetrics:
    location: str
    active_profiles: int = 0
    active_accounts: int = 0
    total_listings: int = 0
    new_listings_24h: int = 0
    new_listings_7d: int = 0
    private_landlord_listings: int = 0
    agent_listings: int = 0
    unknown_landlord_type_listings: int = 0
    contactable_listings: int = 0
    not_contactable_listings: int = 0
    previously_contacted_listings: int = 0
    processing_failures: int = 0
    usable_inventory: int = 0
    conversations: int = 0
    replies: int = 0
    phones: int = 0
    reply_rate_pct: int = 0
    phone_capture_rate_pct: int = 0
    estimated_supported_accounts: int = 0
    current_account_gap: int = 0
    status: str = "insufficient_data"
    evidence: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def get_area_metrics() -> list[dict]:
    """Return deterministic area metrics sorted by actionability."""
    return [metric.to_dict() for metric in _load_area_metrics()]


def area_metrics_summary(limit: int = 5) -> str:
    metrics = _load_area_metrics()
    if not metrics:
        return "No area intelligence data is available yet."

    lines = []
    for metric in metrics[:limit]:
        lines.append(
            f"{metric.location}: {metric.status}, "
            f"{metric.usable_inventory} usable listings, "
            f"{metric.new_listings_7d} new listings in 7d, "
            f"{metric.estimated_supported_accounts} supported accounts, "
            f"{metric.phone_capture_rate_pct}% phone rate"
        )
    return "\n".join(lines)


def answer_area_question(question: str) -> str | None:
    """Answer area/capacity questions deterministically when enough data exists."""
    metrics = _load_area_metrics()
    if not metrics:
        return None

    text = question.lower()
    area = _find_requested_area(text, metrics)

    if area and re.search(r"\bhow\s+many\s+(?:accounts?|sims?|proxies?)\b", text):
        return _answer_area_capacity(area)

    if re.search(
        r"\b(which|what|where)\b.*\b(area|location|borough|city)\b.*\b(next|target|focus|assign)\b",
        text,
    ) or re.search(r"\bnext\s+(?:area|city|location)\b", text):
        return _answer_next_area(metrics)

    if re.search(r"\b(?:area|location|borough|city).*\b(exhausted|pause|maintain|expand)\b", text):
        return _answer_area_status(metrics, area)

    return None


def _load_area_metrics(now: datetime | None = None) -> list[AreaMetrics]:
    now = now or datetime.utcnow()
    day_ago = now - timedelta(days=1)
    week_ago = now - timedelta(days=7)
    areas: dict[str, AreaMetrics] = {}
    active_account_ids_by_area: dict[str, set[int]] = {}

    with SessionLocal() as db:
        profiles = (
            db.query(SearchProfile)
            .options(joinedload(SearchProfile.account))
            .all()
        )
        for profile in profiles:
            metric = areas.setdefault(profile.location, AreaMetrics(profile.location))
            if profile.active:
                metric.active_profiles += 1
            if profile.active and profile.account and profile.account.active:
                active_account_ids_by_area.setdefault(profile.location, set()).add(
                    profile.account.id
                )

        listings = (
            db.query(Listing)
            .options(
                joinedload(Listing.search_profile),
                joinedload(Listing.landlord),
                joinedload(Listing.conversations),
            )
            .all()
        )

    for listing in listings:
        if not listing.search_profile:
            continue
        metric = areas.setdefault(
            listing.search_profile.location,
            AreaMetrics(listing.search_profile.location),
        )
        _apply_listing(metric, listing, day_ago, week_ago)

    for metric in areas.values():
        metric.active_accounts = len(
            active_account_ids_by_area.get(metric.location, set())
        )
        _finalize_metric(metric)

    return sorted(areas.values(), key=_sort_key)


def _apply_listing(
    metric: AreaMetrics,
    listing: Listing,
    day_ago: datetime,
    week_ago: datetime,
) -> None:
    metric.total_listings += 1

    if listing.first_seen and listing.first_seen >= day_ago:
        metric.new_listings_24h += 1
    if listing.first_seen and listing.first_seen >= week_ago:
        metric.new_listings_7d += 1

    landlord = listing.landlord
    if landlord and landlord.is_agent:
        metric.agent_listings += 1
    elif landlord:
        metric.private_landlord_listings += 1
    else:
        metric.unknown_landlord_type_listings += 1

    if listing.contacted or listing.message_sent:
        metric.previously_contacted_listings += 1
    if listing.processing_failed:
        metric.processing_failures += 1

    is_agent = bool(landlord and landlord.is_agent)
    is_usable = (
        not listing.message_sent
        and not listing.processing_failed
        and not listing.skip_reason
        and not listing.listing_archived
        and not is_agent
    )
    if is_usable:
        metric.usable_inventory += 1
        metric.contactable_listings += 1
    else:
        metric.not_contactable_listings += 1

    for conversation in listing.conversations:
        metric.conversations += 1
        if conversation.last_processed_message:
            metric.replies += 1
        if conversation.extracted_phone:
            metric.phones += 1


def _finalize_metric(metric: AreaMetrics) -> None:
    if metric.conversations:
        metric.reply_rate_pct = round((metric.replies / metric.conversations) * 100)
        metric.phone_capture_rate_pct = round((metric.phones / metric.conversations) * 100)

    recent_daily_supply = metric.new_listings_7d / 7
    supply_supported = math.floor(
        recent_daily_supply / max(RULES["messages_per_account_per_day"], 1)
    )
    inventory_supported = math.floor(
        metric.usable_inventory / max(RULES["messages_per_account_per_day"], 1)
    )
    metric.estimated_supported_accounts = max(supply_supported, inventory_supported)
    metric.current_account_gap = metric.estimated_supported_accounts - metric.active_accounts

    if metric.total_listings < MIN_TOTAL_LISTINGS_FOR_DECISION:
        metric.status = "insufficient_data"
        metric.evidence = "Needs more discovered listings before making an allocation decision."
    elif metric.usable_inventory == 0 and metric.new_listings_7d == 0:
        metric.status = "pause"
        metric.evidence = "No usable inventory and no recent listing supply."
    elif metric.conversations < MIN_CONTACTED_FOR_RATE:
        metric.status = "insufficient_data"
        metric.evidence = "Needs more contacted leads before conversion rates are reliable."
    elif metric.phone_capture_rate_pct >= 20 and metric.current_account_gap > 0:
        metric.status = "expand"
        metric.evidence = "Phone capture rate is healthy and measured supply can support more accounts."
    elif metric.usable_inventory >= max(metric.active_accounts, 1):
        metric.status = "maintain"
        metric.evidence = "Usable inventory remains available for current allocation."
    else:
        metric.status = "pause"
        metric.evidence = "Current allocation is at or above measured usable supply."


def _sort_key(metric: AreaMetrics) -> tuple:
    status_rank = {"expand": 0, "maintain": 1, "insufficient_data": 2, "pause": 3}
    return (
        status_rank.get(metric.status, 9),
        -metric.phone_capture_rate_pct,
        -metric.usable_inventory,
        metric.location.lower(),
    )


def _find_requested_area(text: str, metrics: list[AreaMetrics]) -> AreaMetrics | None:
    for metric in metrics:
        if metric.location.lower() in text:
            return metric

    compact_text = re.sub(r"[^a-z0-9]+", " ", text).strip()
    for metric in metrics:
        tokens = [token for token in re.findall(r"[a-z0-9]+", metric.location.lower()) if len(token) > 2]
        if tokens and all(token in compact_text for token in tokens):
            return metric
    return None


def _answer_area_capacity(metric: AreaMetrics) -> str:
    accounts = metric.estimated_supported_accounts
    sims = accounts
    proxies = math.ceil(accounts / max(RULES["max_accounts_per_proxy"], 1))

    return (
        f"**{metric.location} capacity**\n"
        f"- Status: {metric.status}\n"
        f"- Usable inventory: {metric.usable_inventory} listings\n"
        f"- New listings in the last 7 days: {metric.new_listings_7d}\n"
        f"- Estimated supported accounts: {accounts}\n"
        f"- SIMs justified by measured supply: {sims}\n"
        f"- Proxies justified at {RULES['max_accounts_per_proxy']} accounts/proxy: {proxies}\n\n"
        f"{metric.evidence}"
    )


def _answer_next_area(metrics: list[AreaMetrics]) -> str:
    expandable = [metric for metric in metrics if metric.status == "expand"]
    candidates = expandable or [metric for metric in metrics if metric.status == "maintain"]

    if not candidates:
        return (
            "**Next area recommendation**\n"
            "No area has enough measured supply and conversion data to justify expansion yet.\n\n"
            "Keep collecting listing and outcome data until at least one area has reliable inventory and conversion metrics."
        )

    best = candidates[0]
    return (
        f"**Next area recommendation: {best.location}**\n"
        f"- Status: {best.status}\n"
        f"- Usable inventory: {best.usable_inventory} listings\n"
        f"- New listings in the last 7 days: {best.new_listings_7d}\n"
        f"- Phone capture rate: {best.phone_capture_rate_pct}%\n"
        f"- Estimated supported accounts: {best.estimated_supported_accounts}\n"
        f"- Current active accounts: {best.active_accounts}\n\n"
        f"{best.evidence}"
    )


def _answer_area_status(metrics: list[AreaMetrics], area: AreaMetrics | None) -> str:
    selected = [area] if area else metrics[:5]
    lines = ["**Area status**"]
    for metric in selected:
        lines.append(
            f"- {metric.location}: {metric.status} "
            f"({metric.usable_inventory} usable, {metric.new_listings_7d} new in 7d, "
            f"{metric.phone_capture_rate_pct}% phone rate)"
        )
    return "\n".join(lines)
