"""Placement ranking for the SIM allocator (_ranked_areas).

Regression for the contention-blind allocator that recycled fresh accounts back
into saturated, already-established areas (e.g. Chigwell) where a newcomer gets
~0 inventory, while ignoring uncontested areas that had real supply but no
conversation history yet (status=insufficient_data, score=0).
"""
from app.advisor.area_intelligence import AreaMetrics
from app.services.sim_allocator import _ranked_areas


def _area(location, *, total_listings, active_accounts, gap, phone_rate=0, score=0.0):
    m = AreaMetrics(location)
    m.total_listings = total_listings
    m.active_accounts = active_accounts
    m.current_account_gap = gap
    m.phone_capture_rate_pct = phone_rate
    m.score = score
    return m


def _allocatable(metrics):
    return {m.location: {} for m in metrics}


def test_uncontested_area_with_no_conversations_is_placeable():
    # The old bug: this area has real supply and room, but score=0 because it
    # has no conversations yet -> was excluded entirely. It must now qualify.
    fresh = _area("Lewisham", total_listings=300, active_accounts=0, gap=4, phone_rate=0, score=0.0)
    ranked = _ranked_areas([fresh], _allocatable([fresh]))
    assert [m.location for m in ranked] == ["Lewisham"]


def test_least_contested_area_beats_high_score_saturated_area():
    # Chigwell has a huge conversion-weighted score, but 3 accounts already work
    # it. A newcomer should be sent to the uncontested area instead.
    saturated = _area("Chigwell", total_listings=500, active_accounts=3, gap=2, phone_rate=44, score=4000.0)
    uncontested = _area("Lewisham", total_listings=300, active_accounts=0, gap=4, phone_rate=0, score=0.0)
    ranked = _ranked_areas([saturated, uncontested], _allocatable([saturated, uncontested]))
    assert ranked[0].location == "Lewisham"
    assert ranked[-1].location == "Chigwell"


def test_ordering_prefers_fewest_accounts_then_largest_gap():
    big = _area("Lewisham", total_listings=300, active_accounts=0, gap=4)
    small = _area("Peckham", total_listings=200, active_accounts=0, gap=2)
    contested = _area("Chigwell", total_listings=500, active_accounts=3, gap=5, phone_rate=44)
    ranked = _ranked_areas([contested, small, big], _allocatable([big, small, contested]))
    assert [m.location for m in ranked] == ["Lewisham", "Peckham", "Chigwell"]


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
