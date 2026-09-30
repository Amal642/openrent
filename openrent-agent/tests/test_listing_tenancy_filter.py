"""Short-let detection on listing pages (parse_listing_metadata).

Business rule (2026-09-30): a 6-month minimum tenancy is a normal UK long let
and must NOT be skipped; minimums of 1-5 months are still treated as short lets.
"""
import pytest

from app.openrent.listing_metadata import (
    MIN_ACCEPTED_TENANCY_MONTHS,
    parse_listing_metadata,
)


def _parse(body):
    return parse_listing_metadata("", body_text=body, page_title="2 Bed Flat, Ealing")


def test_threshold_is_six_months():
    assert MIN_ACCEPTED_TENANCY_MONTHS == 6


@pytest.mark.parametrize(
    "body, months",
    [
        ("Minimum Tenancy: 6 Months", 6),
        ("Minimum Tenancy\n6 Months", 6),
        ("Min Tenancy: 12 months", 12),
        ("Minimum Tenancy: 1 Year", 12),
        ("Minimum Tenancy: 8 Months", 8),
    ],
)
def test_six_months_or_more_is_long_let(body, months):
    meta = _parse(body)
    assert meta["min_tenancy_months"] == months
    assert meta["is_short_term"] is False


@pytest.mark.parametrize("months", [1, 2, 3, 5])
def test_under_six_months_is_short_let(months):
    meta = _parse(f"Minimum Tenancy: {months} Months")
    assert meta["min_tenancy_months"] == months
    assert meta["is_short_term"] is True


@pytest.mark.parametrize(
    "body",
    [
        "Short term let available from October",
        "This is a holiday let in central London",
        "Serviced accommodation, bills included",
        "Available as a short-term let only",
    ],
)
def test_explicit_short_let_keywords_still_skip(body):
    assert _parse(body)["is_short_term"] is True


@pytest.mark.parametrize(
    "body",
    [
        "No short term lets. Minimum Tenancy: 12 Months",
        "Not a short let, looking for long-term tenants",
        "We don't do short-term lets",
        "Minimum Tenancy: 6 Months. No short term lets please.",
    ],
)
def test_negated_short_let_mentions_are_long_lets(body):
    assert _parse(body)["is_short_term"] is False


def test_negation_in_previous_sentence_does_not_mask_real_short_let():
    # "No pets." is a different sentence; the short-let statement still counts.
    assert _parse("No pets. Short term let available")["is_short_term"] is True


def test_no_tenancy_info_is_not_short_let():
    meta = _parse("Lovely 2 bed flat near the station")
    assert meta["min_tenancy_months"] is None
    assert meta["is_short_term"] is False
