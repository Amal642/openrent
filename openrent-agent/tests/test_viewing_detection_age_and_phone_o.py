"""2026-10-08 lead-leak fixes: no AI viewing detection on dead threads (old
"today" was read as the current date, moving 17 old viewings to the present),
and landlord numbers typed with a letter o for the zero ("o7484318755")."""
from datetime import datetime, timedelta, timezone

from scripts.process_replies import _should_run_viewing_detection
from app.ai.extractors import regex_extract_phone

NOW = datetime(2026, 10, 8, 9, 0, tzinfo=timezone.utc)


def test_old_landlord_message_skips_viewing_detection():
    old = NOW - timedelta(days=30)
    assert _should_run_viewing_detection({}, has_new_landlord_message=True, latest_landlord_at=old, now=NOW) is False


def test_recent_or_unknown_landlord_message_still_detects():
    recent = NOW - timedelta(hours=3)
    assert _should_run_viewing_detection({}, has_new_landlord_message=True, latest_landlord_at=recent, now=NOW) is True
    assert _should_run_viewing_detection({}, has_new_landlord_message=True, latest_landlord_at=None, now=NOW) is True
    naive_recent = (NOW - timedelta(hours=3)).replace(tzinfo=None)
    assert _should_run_viewing_detection({}, has_new_landlord_message=True, latest_landlord_at=naive_recent, now=NOW) is True


def test_letter_o_for_zero_is_read():
    assert regex_extract_phone(["yes he can reach me on o7484318755. I'll wait"]) == "07484318755"
    assert regex_extract_phone(["call O7700 900 123 any time"]) == "07700900123"


def test_letter_o_inside_words_is_not_a_number():
    assert regex_extract_phone(["No7 is the flat, ref 7123456789"]) is None
    assert regex_extract_phone(["ring 07911 123456"]) == "07911123456"
