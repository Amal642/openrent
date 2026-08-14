"""Banner datetime parsing — covers both OpenRent confirmation formats.

The '...August 3:00 PM at <address>' case (time right after month, 'at' before
the address) was the 823/day parse-failure that left viewing_datetime null.
"""
from datetime import datetime

from app.openrent.banner_parser import parse_banner_datetime

NOW = datetime(2026, 8, 1, 9, 0)


def test_format_time_after_at():
    r = parse_banner_datetime("Viewing confirmed for Sunday 7th June at 1:00 PM", now=NOW)
    assert r == datetime(2026, 6, 7, 13, 0)


def test_format_time_before_at_address():
    # The real failing banner.
    r = parse_banner_datetime(
        "Viewing confirmed for Wednesday 12th August 3:00 PM at 2 Aston Close, "
        "Hemel Hempstead, HP3 9HJ",
        now=NOW,
    )
    assert r == datetime(2026, 8, 12, 15, 0)


def test_am_and_year():
    r = parse_banner_datetime("Viewing confirmed for Monday 3rd March 2027 9:30 AM", now=NOW)
    assert r == datetime(2027, 3, 3, 9, 30)


def test_midnight_and_noon_suffix():
    assert parse_banner_datetime("Viewing confirmed for 5th May at 12:00 PM", now=NOW) == datetime(2026, 5, 5, 12, 0)
    assert parse_banner_datetime("Viewing confirmed for 5th May 12:00 AM", now=NOW) == datetime(2026, 5, 5, 0, 0)


def test_non_banner_returns_none():
    assert parse_banner_datetime("Hi, when would suit you for a viewing?", now=NOW) is None
    assert parse_banner_datetime("", now=NOW) is None
