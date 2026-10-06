"""
Automated SIM allocation engine.

Assigns unallocated accounts (active, no active search profiles) to the
highest-scoring allocatable area (any region), and rebalances accounts stuck
in exhausted (pause) areas.

Entry point: run_allocation(dry_run=False)
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy import text

from app.advisor.area_defaults import get_area_defaults
from app.advisor.area_intelligence import (
    MIN_ACCOUNTS_FOR_SCORING,
    MIN_TOTAL_LISTINGS_FOR_DECISION,
    AreaMetrics,
    _load_area_metrics,
)
from app.db.connection import SessionLocal
from app.db.repository import create_search_profile
from app.utils.logger import logger


# An area only counts as exhausted (worth moving its account away) when it is
# paused AND its recent supply is below ~1 new listing/day. "pause" alone also
# fires when a single owner is harvesting its area exactly (usable backlog 0,
# supply supports 1 account), which is the healthy steady state -- moving that
# owner into another account's area (2026-09-28: 28->Woolwich, 31->Acton,
# 34->Lewisham) only created double coverage.
EXHAUSTED_MAX_NEW_LISTINGS_7D = 7

# A freshly assigned area has had no time to show supply (its 7-day count
# starts at ~0), so it reads as "exhausted" the next morning. Leave an
# account's areas alone until its newest active profile is this old; on
# 2026-10-06 the dry run would have moved two 1-day-old accounts.
REBALANCE_GRACE_DAYS = 7


def _exhausted_locations(metrics: list[AreaMetrics]) -> set[str]:
    return {
        m.location
        for m in metrics
        if m.status == "pause" and m.new_listings_7d < EXHAUSTED_MAX_NEW_LISTINGS_7D
    }


def run_allocation(dry_run: bool = False) -> dict:
    """
    Assign pool SIMs and rebalance exhausted ones.
    Returns a summary dict safe to return as JSON.
    """
    metrics = _load_area_metrics()
    # Only allocatable locations are valid SIM targets (spend guardrail); the
    # metrics list still contains every active area for reporting.
    area_defaults = get_area_defaults(allocatable_only=True)
    paused_locations = _exhausted_locations(metrics)

    assigned: list[dict] = []
    rebalanced: list[dict] = []
    skipped: list[dict] = []
    warnings: list[str] = []

    with SessionLocal() as db:
        pool_accounts = _get_pool_accounts(db)
        rebalance_candidates = _get_rebalance_candidates(db, paused_locations)
        owned = _owned_locations(db)

    # --- assign pool accounts ---
    for acc_id, email in pool_accounts:
        ranked = _ranked_areas(metrics, area_defaults, owned=owned)
        if not ranked:
            msg = "SIM pool has accounts waiting but no allocatable area currently has supply."
            if msg not in warnings:
                warnings.append(msg)
            skipped.append({"account": email, "reason": "No area qualifies for assignment"})
            continue

        best = ranked[0]
        if best.location not in area_defaults:
            skipped.append({"account": email, "reason": f"No defaults config for {best.location}"})
            logger.warning(f"SIM_ALLOCATOR no defaults for area={best.location}")
            continue

        if not dry_run:
            defaults = area_defaults[best.location]
            create_search_profile(
                account_id=acc_id,
                location=best.location,
                price_min=defaults["price_min"],
                price_max=defaults["price_max"],
                bedrooms_min=defaults["bedrooms_min"],
                bedrooms_max=defaults["bedrooms_max"],
                area=defaults["area"],
            )

        assigned.append({
            "account": email,
            "area": best.location,
            "score": best.score,
            "phone_rate_pct": best.phone_capture_rate_pct,
            "new_listings_7d": best.new_listings_7d,
        })
        logger.info(
            f"SIM_ALLOCATOR assigned account={email} area={best.location} "
            f"score={best.score} dry_run={dry_run}"
        )

        # Update in-memory count so the next SIM redistributes correctly
        owned.add(best.location)
        best.active_accounts += 1
        best.current_account_gap -= 1
        best.score = _recompute_score(best)

    # --- rebalance exhausted accounts ---
    for candidate in rebalance_candidates:
        acc_id = candidate["id"]
        email = candidate["email"]
        old_locations = [p["location"] for p in candidate["profiles"]]
        old_profile_ids = [p["profile_id"] for p in candidate["profiles"]]

        ranked = _ranked_areas(metrics, area_defaults, owned=owned)
        if not ranked:
            skipped.append({"account": email, "reason": "All areas paused, cannot rebalance"})
            continue

        best = ranked[0]
        if best.location not in area_defaults:
            skipped.append({"account": email, "reason": f"No defaults config for {best.location}"})
            continue

        if not dry_run:
            _deactivate_profiles(old_profile_ids)
            defaults = area_defaults[best.location]
            create_search_profile(
                account_id=acc_id,
                location=best.location,
                price_min=defaults["price_min"],
                price_max=defaults["price_max"],
                bedrooms_min=defaults["bedrooms_min"],
                bedrooms_max=defaults["bedrooms_max"],
                area=defaults["area"],
            )

        rebalanced.append({
            "account": email,
            "from_areas": old_locations,
            "to_area": best.location,
            "score": best.score,
            "phone_rate_pct": best.phone_capture_rate_pct,
        })
        logger.info(
            f"SIM_ALLOCATOR rebalanced account={email} "
            f"from={old_locations} to={best.location} dry_run={dry_run}"
        )

        owned.add(best.location)
        best.active_accounts += 1
        best.current_account_gap -= 1
        best.score = _recompute_score(best)

    return {
        "dry_run": dry_run,
        "assigned": assigned,
        "rebalanced": rebalanced,
        "skipped": skipped,
        "warnings": warnings,
    }


# --- helpers ---

def _get_pool_accounts(db) -> list[tuple]:
    """Active accounts with no active search profiles."""
    return db.execute(text(
        "SELECT a.id, a.email FROM accounts a "
        "WHERE a.active = true AND a.deleted_at IS NULL "
        "AND NOT EXISTS ("
        "  SELECT 1 FROM search_profiles sp "
        "  WHERE sp.account_id = a.id AND sp.active = true"
        ") ORDER BY a.id"
    )).fetchall()


def _owned_locations(db) -> set[str]:
    """Locations an active account is already assigned to. Area metrics count
    accounts from recent activity, so an owner assigned today does not show
    up there yet; profiles are the source of truth for ownership."""
    return {
        row[0]
        for row in db.execute(text(
            "SELECT DISTINCT sp.location FROM search_profiles sp "
            "JOIN accounts a ON a.id = sp.account_id "
            "WHERE sp.active = true AND a.active = true AND a.deleted_at IS NULL"
        )).fetchall()
    }


def _get_rebalance_candidates(db, paused_locations: set[str]) -> list[dict]:
    """Active accounts where every active profile is in a paused area, skipping
    accounts still inside the REBALANCE_GRACE_DAYS window."""
    if not paused_locations:
        return []

    rows = db.execute(text(
        "SELECT a.id, a.email, sp.id as profile_id, sp.location, sp.created_at "
        "FROM accounts a "
        "JOIN search_profiles sp ON sp.account_id = a.id "
        "WHERE a.active = true AND a.deleted_at IS NULL AND sp.active = true "
        "ORDER BY a.id"
    )).fetchall()
    return _rebalance_candidates_from_rows(rows, paused_locations, datetime.utcnow())


def _rebalance_candidates_from_rows(rows, paused_locations: set[str], now: datetime) -> list[dict]:
    account_profiles: dict[int, list] = defaultdict(list)
    account_emails: dict[int, str] = {}
    newest: dict[int, datetime] = {}
    for row in rows:
        acc_id, email, profile_id, location, created_at = row
        account_profiles[acc_id].append({"profile_id": profile_id, "location": location})
        account_emails[acc_id] = email
        if created_at and (acc_id not in newest or created_at > newest[acc_id]):
            newest[acc_id] = created_at

    grace = timedelta(days=REBALANCE_GRACE_DAYS)
    candidates = []
    for acc_id, profiles in account_profiles.items():
        if acc_id in newest and now - newest[acc_id] < grace:
            continue
        if all(p["location"] in paused_locations for p in profiles):
            candidates.append({
                "id": acc_id,
                "email": account_emails[acc_id],
                "profiles": profiles,
            })
    return candidates


def _ranked_areas(
    metrics: list[AreaMetrics], allocatable: dict, owned: set[str] | None = None
) -> list[AreaMetrics]:
    """Allocatable areas eligible for a new SIM, best target first.

    Contention-aware placement. Two facts drive this:

    1. Listing IDs are globally unique, so an area already worked by other
       accounts yields ~nothing to a newcomer — incumbents scrape new supply
       first. So we only place into UNCONTESTED areas, never the one with
       the highest raw supply.
    2. A fresh, uncontested area has no conversations yet, so its
       area-intelligence `status` is `insufficient_data` and its `score` is 0.
       Ranking by `score` (the old behaviour) therefore excluded every
       uncontested area and could only recycle accounts back into the
       saturated, already-established ones. We must not gate on `score` here.

    Eligibility requires real, discovered supply
    (`total_listings >= MIN_TOTAL_LISTINGS_FOR_DECISION`) and NO active
    account already working the area: a listing can only be messaged by the
    account whose profile discovered it, so a second owner just races the
    first for the same new listings. `current_account_gap` is not required
    because an unowned area's 7-day supply is ~0 (nobody searched it), which
    would make every unowned area ineligible. Ranking prefers the freshest
    recent supply, then spare capacity, then proven phone rate, then
    historical volume.
    """
    owned = owned or set()
    eligible = [
        m for m in metrics
        if m.location in allocatable
        and m.total_listings >= MIN_TOTAL_LISTINGS_FOR_DECISION
        and m.active_accounts == 0
        and m.location not in owned
    ]
    return sorted(
        eligible,
        key=lambda m: (
            -m.new_listings_7d,
            -m.current_account_gap,
            -m.phone_capture_rate_pct,
            -m.total_listings,
        ),
    )


def _recompute_score(metric: AreaMetrics) -> float:
    return round(
        metric.phone_capture_rate_pct
        * (metric.new_listings_7d / max(metric.active_accounts, MIN_ACCOUNTS_FOR_SCORING)),
        1,
    )


def _deactivate_profiles(profile_ids: list[int]) -> None:
    with SessionLocal() as db:
        db.execute(
            text("UPDATE search_profiles SET active = false WHERE id = ANY(:ids)"),
            {"ids": profile_ids},
        )
        db.commit()
