"""
ARM_A baseline test suite — 10 targeted tests for seeded mutations.

Each test asserts CORRECT behaviour of a real OpenRent function.
These tests pass against the current codebase; the mutations in
testfix/seeds.py make each one fail in a controlled, recoverable way.

DO NOT add MVP evidence claims here. This file measures fix-rate
infrastructure only.
"""

from datetime import datetime

import pytest

from app.ai.conversation_memory import (
    detect_landlord_attitude,
    landlord_messages,
    outbound_count,
)
from app.ai.extractors import regex_extract_phone
from app.ai.replies import (
    FALLBACK_DISTANT_LOCATIONS,
    _fallback_distant_location,
    _normalize_place_name,
)
from app.ai.stages import extract_viewing_datetime
from app.ai.validators import is_valid_reply, remove_unapproved_phone_numbers
from app.utils.phone import normalize_uk_phone


# ── 1: regex/pattern missing case ────────────────────────────────────────────
def test_regex_extract_phone_uk_mobile_11_digits():
    """Standard UK mobile (07x, 11 digits) must be extracted."""
    assert regex_extract_phone(["My number is 07911123456"]) == "07911123456"


# ── 2: wrong conditional ──────────────────────────────────────────────────────
def test_detect_landlord_attitude_aggressive_beats_polite_opener():
    """Aggressive pattern takes priority over a polite opener in the same message."""
    messages = [{"sender": "landlord", "message": "Thanks but stop messaging me please"}]
    assert detect_landlord_attitude(messages) == "aggressive"


# ── 3: off-by-one / date window ───────────────────────────────────────────────
def test_extract_viewing_datetime_same_weekday_means_next_week():
    """If the named weekday is today, the appointment is 7 days away, not 0."""
    now = datetime(2026, 5, 18, 9, 0)   # Monday
    messages = [{"sender": "landlord", "message": "See you Monday at 3pm, confirmed"}]
    result = extract_viewing_datetime(messages, now=now)
    assert result == datetime(2026, 5, 25, 15, 0)


# ── 4: missing None handling ──────────────────────────────────────────────────
def test_outbound_count_handles_none_messages():
    """None messages argument must return 0, not raise."""
    assert outbound_count(None) == 0


# ── 5: wrong status transition ────────────────────────────────────────────────
def test_is_valid_reply_empty_string_is_invalid():
    """Empty string is not a valid reply."""
    assert is_valid_reply("") is False


# ── 6: duplicate-counting issue ───────────────────────────────────────────────
def test_landlord_messages_excludes_tenant_messages():
    """Tenant messages must not be included in the landlord message list."""
    messages = [
        {"sender": "landlord", "message": "Hi, when can you view?"},
        {"sender": "tenant", "message": "Monday works for me"},
        {"sender": "landlord", "message": "Great, see you then"},
    ]
    result = landlord_messages(messages)
    assert len(result) == 2


# ── 7: parser edge case ───────────────────────────────────────────────────────
def test_normalize_uk_phone_plus44_prefix_converts_correctly():
    """+447... must become 07..., preserving all remaining digits."""
    assert normalize_uk_phone("+447911123456") == "07911123456"


# ── 8: return-value mismatch ─────────────────────────────────────────────────
def test_fallback_distant_location_varies_by_input():
    """Fallback location must be input-dependent, not always the hardcoded default."""
    result = _fallback_distant_location("London")
    assert result in FALLBACK_DISTANT_LOCATIONS
    assert result != "Manchester"


# ── 9: exception path ────────────────────────────────────────────────────────
def test_remove_unapproved_phone_numbers_none_input_returns_none():
    """None reply must be returned as-is without raising."""
    assert remove_unapproved_phone_numbers(None) is None


# ── 10: boundary value ───────────────────────────────────────────────────────
def test_normalize_place_name_truncates_four_words_to_three():
    """A four-word place name must be truncated to three words, not two."""
    assert _normalize_place_name("Little Hadham Village East") == "Little Hadham Village"
