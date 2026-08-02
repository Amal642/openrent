"""
Automated SIM allocation engine.

Assigns unallocated accounts (active, no active search profiles) to the
highest-scoring allocatable area (any region), and rebalances accounts stuck
in exhausted (pause) areas.

Entry point: run_allocation(dry_run=False)
"""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import text

from app.advisor.area_defaults import get_area_defaults
from app.advisor.area_intelligence import (
    MIN_ACCOUNTS_FOR_SCORING,
    AreaMetrics,
    _load_area_metrics,
)
from app.db.connection import SessionLocal
from app.db.repository import create_search_profile
from app.utils.logger import logger


def run_allocation(dry_run: bool = False) -> dict:
    """
    Assign pool SIMs and rebalance exhausted ones.
    Returns a summary dict safe to return as JSON.
    """
    metrics = _load_area_metrics()
    # Only allocatable locations are valid SIM targets (spend guardrail); the
    # metrics list still contains every active area for reporting.
    area_defaults = get_area_defaults(allocatable_only=True)
    paused_locations = {m.location for m in metrics if m.status == "pause"}

    assigned: list[dict] = []
    rebalanced: list[dict] = []
    skipped: list[dict] = []
    warnings: list[str] = []

    with SessionLocal() as db:
        pool_accounts = _get_pool_accounts(db)
        rebalance_candidates = _get_rebalance_candidates(db, paused_locations)

    # --- assign pool accounts ---
    for acc_id, email in pool_accounts:
        ranked = _ranked_areas(metrics, area_defaults)
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
        best.active_accounts += 1
        best.score = _recompute_score(best)

    # --- rebalance exhausted accounts ---
    for candidate in rebalance_candidates:
        acc_id = candidate["id"]
        email = candidate["email"]
        old_locations = [p["location"] for p in candidate["profiles"]]
        old_profile_ids = [p["profile_id"] for p in candidate["profiles"]]

        ranked = _ranked_areas(metrics, area_defaults)
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

        best.active_accounts += 1
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


def _get_rebalance_candidates(db, paused_locations: set[str]) -> list[dict]:
    """Active accounts where every active profile is in a paused area."""
    if not paused_locations:
        return []

    rows = db.execute(text(
        "SELECT a.id, a.email, sp.id as profile_id, sp.location "
        "FROM accounts a "
        "JOIN search_profiles sp ON sp.account_id = a.id "
        "WHERE a.active = true AND a.deleted_at IS NULL AND sp.active = true "
        "ORDER BY a.id"
    )).fetchall()

    account_profiles: dict[int, list] = defaultdict(list)
    account_emails: dict[int, str] = {}
    for row in rows:
        acc_id, email, profile_id, location = row
        account_profiles[acc_id].append({"profile_id": profile_id, "location": location})
        account_emails[acc_id] = email

    candidates = []
    for acc_id, profiles in account_profiles.items():
        if all(p["location"] in paused_locations for p in profiles):
            candidates.append({
                "id": acc_id,
                "email": account_emails[acc_id],
                "profiles": profiles,
            })
    return candidates


def _ranked_areas(metrics: list[AreaMetrics], allocatable: dict) -> list[AreaMetrics]:
    """Allocatable areas eligible for assignment, sorted by score descending."""
    return sorted(
        (m for m in metrics if m.score > 0 and m.location in allocatable),
        key=lambda m: m.score,
        reverse=True,
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
