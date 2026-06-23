from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.utils.scheduling import is_operating_hours, is_uk_outreach_window


UK_TZ = ZoneInfo("Europe/London")


def uk_time(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 6, 23, hour, minute, tzinfo=UK_TZ)


def test_sending_is_allowed_until_2300_uk_time():
    assert is_operating_hours(uk_time(22, 59))
    assert is_uk_outreach_window(uk_time(22, 59))


def test_sending_is_blocked_at_2300_uk_time():
    assert not is_operating_hours(uk_time(23, 0))
    assert not is_uk_outreach_window(uk_time(23, 0))


def test_cutoff_uses_uk_time_when_input_is_utc():
    # June is BST, so 22:00 UTC is 23:00 in the UK.
    cutoff_utc = datetime(2026, 6, 23, 22, 0, tzinfo=timezone.utc)

    assert not is_operating_hours(cutoff_utc)
    assert not is_uk_outreach_window(cutoff_utc)
