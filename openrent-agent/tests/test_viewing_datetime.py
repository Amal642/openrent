"""P3: viewing-datetime extraction regressions.

Every 'should parse' case below is a real landlord message the old extractor
missed (from the audit: 88% of confirmed-viewing/null-datetime threads actually
contained a parseable time). The 'must not parse' cases guard against picking up
bare numbers as phantom times.
"""
from datetime import datetime, timedelta

from app.ai.stages import extract_viewing_datetime

NOW = datetime(2026, 8, 13, 9, 0)  # Thu 09:00 (fixed for determinism)


def _dt(text, now=NOW):
    return extract_viewing_datetime([{"sender": "landlord", "message": text}], now=now)


def test_ampm_with_day_but_no_viewing_keyword():
    r = _dt("Today @3pm I am here.")
    assert r is not None and (r.hour, r.minute) == (15, 0) and r.date() == NOW.date()


def test_time_range_with_today():
    r = _dt("6-6:30pm today")
    assert r is not None and (r.hour, r.minute) == (18, 30) and r.date() == NOW.date()


def test_dot_separated_minutes_tomorrow():
    r = _dt("Please confirm your attendance for tomorrow's viewing at 5.30pm")
    assert r is not None and (r.hour, r.minute) == (17, 30)
    assert r.date() == (NOW + timedelta(days=1)).date()


def test_plural_viewings_keyword():
    r = _dt("evening viewings from 7:30pm Tue to Thur")
    assert r is not None and (r.hour, r.minute) == (19, 30)


def test_part_of_day_fallback_weekday_evening():
    r = _dt("Happy to do this Thursday or Friday evening")
    assert r is not None and r.hour == 18 and r.weekday() == 3  # Thursday
    assert r > NOW


def test_bare_number_is_not_a_phantom_time():
    assert _dt("I'll contact you in 1 day about the viewing") is None


def test_bare_hour_without_ampm_is_not_a_time():
    assert _dt("I can call you at 2 about the viewing") is None
