"""
ARM_A hard calibration test suite — 7 cases targeting 40-70% first-attempt success.

Properties of each case:
  - ambiguous error signal: the test failure doesn't reveal the exact edit needed
  - multiple plausible wrong fixes exist in the function body
  - at least one case requires knowing codebase conventions not visible in a single function

Covers: wrong candidate order, status-stage ambiguity, phone normalization convention,
        boundary/datetime, edge-case parser, None/fallback, cross-function convention.

All tests assert CORRECT behaviour and must PASS on the current codebase.
The seeded mutations in testfix/seeds_hard.py make each fail in a specific way.
"""

from datetime import datetime, timedelta

import pytest

from app.ai.conversation_memory import detect_landlord_attitude
from app.ai.extractors import regex_extract_phone
from app.ai.stages import detect_stage, extract_viewing_datetime
from app.db.status import VIEWING_BOOKED, VIEWING_DISCUSSION
from app.utils.phone import normalize_uk_phone


# ── hard_001: wrong candidate selection/order ─────────────────────────────────
def test_extract_viewing_datetime_uses_last_confirmed_time_not_first():
    """When multiple times appear across messages, the LAST confirmed time is used."""
    now = datetime(2026, 5, 18, 9, 0)  # Monday
    messages = [
        {"sender": "landlord", "message": "I can do 2pm or 5pm on Tuesday"},
        {"sender": "tenant", "message": "5pm works better for me"},
        {"sender": "landlord", "message": "Confirmed, see you Tuesday at 5pm"},
    ]
    result = extract_viewing_datetime(messages, now=now)
    assert result == datetime(2026, 5, 19, 17, 0)   # Tuesday 5pm — not 2pm


# ── hard_002: status-stage logic ambiguity ────────────────────────────────────
def test_detect_stage_confirmed_booking_with_time_returns_viewing_booked():
    """A message with a confirmed booking pattern and a time must return VIEWING_BOOKED."""
    messages = [
        {"sender": "landlord", "message": "That works. Confirmed, see you Thursday at 2pm."},
        {"sender": "tenant", "message": "Perfect."},
    ]
    assert detect_stage(messages) == VIEWING_BOOKED


# ── hard_003: phone normalization convention ──────────────────────────────────
def test_normalize_uk_phone_bare_44_prefix_no_plus():
    """A bare 44-prefixed number (no + sign) must normalise to 07 format."""
    assert normalize_uk_phone("447911123456") == "07911123456"


# ── hard_004: boundary/datetime behaviour ─────────────────────────────────────
def test_detect_landlord_attitude_slow_reply_on_long_gap():
    """A gap of more than 24 hours between landlord messages must return slow_reply."""
    now = datetime(2026, 5, 19, 12, 0)
    messages = [
        {"sender": "landlord", "message": "Hi",
         "created_at": now - timedelta(hours=30)},
        {"sender": "landlord", "message": "Are you still interested?",
         "created_at": now},
    ]
    assert detect_landlord_attitude(messages) == "slow_reply"


# ── hard_005: edge-case parser behaviour ─────────────────────────────────────
def test_regex_extract_phone_preserves_plus_prefix():
    """A +44-prefixed phone number must be returned with the + sign intact."""
    assert regex_extract_phone(["+447911123456"]) == "+447911123456"


# ── hard_006: None/failure fallback behaviour ─────────────────────────────────
def test_extract_viewing_datetime_without_now_does_not_raise():
    """Calling without explicit now must not raise and must return a datetime."""
    messages = [
        {"sender": "landlord", "message": "See you tomorrow at 3pm, confirmed"}
    ]
    result = extract_viewing_datetime(messages)   # no now= argument
    assert result is not None
    assert isinstance(result, datetime)


# ── hard_007: cross-function convention ──────────────────────────────────────
def test_detect_stage_uses_most_recent_message_not_oldest():
    """Stage detection must be driven by the most recent messages.
    An early reschedule request must not override a later confirmed booking."""
    messages = [
        {"sender": "tenant", "message": "Can we reschedule the viewing?"},
        {"sender": "landlord", "message": "Of course, how about Thursday at 2pm?"},
        {"sender": "tenant", "message": "Thursday 2pm works, confirmed"},
        {"sender": "landlord", "message": "Great, see you then"},
    ]
    assert detect_stage(messages) == VIEWING_BOOKED
