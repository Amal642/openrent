"""Placement ranking for the SIM allocator (_ranked_areas).

Regression for the contention-blind allocator that recycled fresh accounts back
into saturated, already-established areas (e.g. Chigwell) where a newcomer gets
~0 inventory, while ignoring uncontested areas that had real supply but no
conversation history yet (status=insufficient_data, score=0).
"""
from app.advisor.area_intelligence import AreaMetrics
from app.services.sim_allocator import _exhausted_locations, _ranked_areas


def _area(location, *, total_listings, active_accounts, gap, phone_rate=0, score=0.0,
          new_7d=0, status="maintain"):
    m = AreaMetrics(location)
    m.total_listings = total_listings
    m.active_accounts = active_accounts
    m.current_account_gap = gap
    m.phone_capture_rate_pct = phone_rate
    m.score = score
    m.new_listings_7d = new_7d
    m.status = status
    return m


def _allocatable(metrics):
    return {m.location: {} for m in metrics}


def test_uncontested_area_with_no_conversations_is_placeable():
    # The old bug: this area has real supply and room, but score=0 because it
    # has no conversations yet -> was excluded entirely. It must now qualify.
    fresh = _area("Lewisham", total_listings=300, active_accounts=0, gap=4, phone_rate=0, score=0.0)
    ranked = _ranked_areas([fresh], _allocatable([fresh]))
    assert [m.location for m in ranked] == ["Lewisham"]


def test_uncontested_area_beats_high_score_saturated_area():
    # Chigwell has a huge conversion-weighted score, but 3 accounts already work
    # it. A newcomer should be sent to the uncontested area; Chigwell is not a
    # target at all.
    saturated = _area("Chigwell", total_listings=500, active_accounts=3, gap=2, phone_rate=44, score=4000.0)
    uncontested = _area("Lewisham", total_listings=300, active_accounts=0, gap=4, phone_rate=0, score=0.0)
    ranked = _ranked_areas([saturated, uncontested], _allocatable([saturated, uncontested]))
    assert [m.location for m in ranked] == ["Lewisham"]


def test_ordering_among_uncontested_prefers_largest_gap():
    big = _area("Lewisham", total_listings=300, active_accounts=0, gap=4)
    small = _area("Peckham", total_listings=200, active_accounts=0, gap=2)
    contested = _area("Chigwell", total_listings=500, active_accounts=3, gap=5, phone_rate=44)
    ranked = _ranked_areas([contested, small, big], _allocatable([big, small, contested]))
    assert [m.location for m in ranked] == ["Lewisham", "Peckham"]


def test_area_with_one_owner_is_never_a_target_even_with_spare_gap():
    # 2026-09-28 regression: Woolwich had one owner and gap=7 (the owner's
    # unmessaged backlog), so the allocator moved a second account in. That
    # account can't claim the owner's listings, so it only doubled coverage.
    woolwich = _area("Woolwich", total_listings=777, active_accounts=1, gap=7, phone_rate=22, new_7d=117)
    assert _ranked_areas([woolwich], _allocatable([woolwich])) == []


def test_unowned_area_with_zero_gap_is_placeable():
    # Unowned areas have ~0 measured 7-day supply, so gap is 0; they must
    # still be valid targets or nothing uncontested is ever placeable.
    tottenham = _area("Tottenham", total_listings=115, active_accounts=0, gap=0, new_7d=44)
    assert [m.location for m in _ranked_areas([tottenham], _allocatable([tottenham]))] == ["Tottenham"]


def test_recent_supply_ranks_first_among_uncontested():
    stale = _area("Clapham", total_listings=409, active_accounts=0, gap=0, phone_rate=42, new_7d=0)
    fresh = _area("Purley", total_listings=198, active_accounts=0, gap=0, phone_rate=30, new_7d=54)
    ranked = _ranked_areas([stale, fresh], _allocatable([stale, fresh]))
    assert [m.location for m in ranked] == ["Purley", "Clapham"]


def test_full_area_excluded():
    # No spare capacity (gap <= 0) -> not a placement target.
    full = _area("FullArea", total_listings=100, active_accounts=5, gap=0)
    assert _ranked_areas([full], _allocatable([full])) == []


def test_thin_area_excluded():
    # Too few discovered listings to trust -> not a placement target.
    thin = _area("TinyArea", total_listings=3, active_accounts=0, gap=1)
    assert _ranked_areas([thin], _allocatable([thin])) == []


def test_non_allocatable_area_excluded():
    good = _area("Lewisham", total_listings=300, active_accounts=0, gap=4)
    # allocatable dict does not contain the area -> excluded (spend guardrail).
    assert _ranked_areas([good], {}) == []


def test_exhausted_requires_pause_and_near_zero_recent_supply():
    # A single owner harvesting its area exactly shows status=pause with real
    # supply (Tottenham 44 new/7d). That is healthy, not exhausted.
    harvested = _area("Tottenham", total_listings=115, active_accounts=1, gap=0, new_7d=44, status="pause")
    dry = _area("Barking", total_listings=11, active_accounts=1, gap=-1, new_7d=0, status="pause")
    trickle = _area("Sidcup", total_listings=51, active_accounts=1, gap=-1, new_7d=3, status="pause")
    quiet_but_stocked = _area("Bexley", total_listings=45, active_accounts=1, gap=0, new_7d=0, status="maintain")
    assert _exhausted_locations([harvested, dry, trickle, quiet_but_stocked]) == {"Barking", "Sidcup"}
