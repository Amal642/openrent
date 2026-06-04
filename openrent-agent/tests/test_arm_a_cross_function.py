"""
ARM_A cross-function calibration test suite — 7 cases where the fix is in a helper,
not in the high-level function the test calls.

Each case design:
  - Test calls function A (high-level)
  - Bug is seeded in function B (helper/dependency called by A)
  - ARM_A context = function A's source only → cannot locate bug
  - Demonstrates where cross-function retrieval adds value

Functions involved:
  cross_001: detect_stage       → _recent_messages       (same file: stages.py)
  cross_002: detect_landlord_attitude → landlord_messages (same file: conversation_memory.py)
  cross_003: latest_landlord_asked_for_phone → landlord_asked_for_phone (cross-file: personas.py)
  cross_004: viewing_requested  → _content               (same file: conversation_memory.py)
  cross_005: detect_stage       → _matches_any           (same file: stages.py)
  cross_006: outbound_count     → _sender                (same file: conversation_memory.py)
  cross_007: phone_shared_state → tenant_shared_phone    (cross-file: personas.py)

All tests assert CORRECT behaviour and must PASS on the current codebase.
"""

import pytest

from app.ai.conversation_memory import (
    detect_landlord_attitude,
    latest_landlord_asked_for_phone,
    outbound_count,
    phone_shared_state,
    viewing_requested,
)
from app.ai.stages import detect_stage
from app.db.status import VIEWING_BOOKED, VIEWING_DISCUSSION


# ── cross_001: detect_stage → _recent_messages ─────────────────────────────────
def test_detect_stage_booking_confirmed_after_long_discussion():
    """With 11 messages, stage must be driven by the LAST 8 messages.
    A confirmed booking in messages 9-11 must return VIEWING_BOOKED even though
    the first 8 messages contain only scheduling discussion."""
    messages = [
        {"sender": "tenant",   "message": "Hi, I saw your listing, is it still available?"},
        {"sender": "landlord", "message": "Yes it is. When are you free?"},
        {"sender": "tenant",   "message": "I'm available most evenings"},
        {"sender": "landlord", "message": "What days work best for you?"},
        {"sender": "tenant",   "message": "Weekday evenings or Saturday"},
        {"sender": "landlord", "message": "What about Saturday afternoon?"},
        {"sender": "tenant",   "message": "Saturday could work, what time were you thinking?"},
        {"sender": "landlord", "message": "How about around midday on Saturday?"},
        {"sender": "tenant",   "message": "Saturday midday works for me, confirmed"},
        {"sender": "landlord", "message": "Great, see you Saturday at 12pm"},
        {"sender": "tenant",   "message": "Perfect"},
    ]
    assert detect_stage(messages) == VIEWING_BOOKED


# ── cross_002: detect_landlord_attitude → landlord_messages ────────────────────
def test_detect_landlord_attitude_inbound_aggression_detected():
    """Aggressive messages from 'inbound' sender (OpenRent's label for landlord) must be detected.
    If landlord_messages excludes the 'inbound' sender, the function sees no landlord messages
    and defaults to 'responsive' instead of 'aggressive'."""
    messages = [
        {"sender": "inbound", "message": "stop wasting my time, serious enquiries only"},
    ]
    assert detect_landlord_attitude(messages) == "aggressive"


# ── cross_003: latest_landlord_asked_for_phone → landlord_asked_for_phone ──────
def test_latest_landlord_asked_for_phone_detects_phone_keyword():
    """'Can you send me your phone?' — 'phone' is the only keyword trigger here.
    If landlord_asked_for_phone removes 'phone' from its keyword pattern, this returns False
    even though the intent is clearly a phone request."""
    messages = [
        {"sender": "landlord", "message": "Can you send me your phone?"},
    ]
    assert latest_landlord_asked_for_phone(messages) is True


# ── cross_004: viewing_requested → _content ────────────────────────────────────
def test_viewing_requested_finds_keyword_in_message_key():
    """viewing_requested must find 'viewing' from messages stored under the 'message' key.
    If _content stops reading the 'message' key (uses wrong field), this returns False."""
    messages = [
        {"sender": "landlord", "message": "When would you like to come for a viewing?"}
    ]
    assert viewing_requested(messages) is True


# ── cross_005: detect_stage → _matches_any ─────────────────────────────────────
def test_detect_stage_single_booked_pattern_is_sufficient():
    """A single BOOKED pattern match must be enough to trigger booking detection.
    _matches_any must use any() across patterns, not all(). With all(), no realistic message
    can match every booked pattern, so VIEWING_BOOKED is never returned."""
    messages = [
        {"sender": "landlord", "message": "Confirmed, see you Thursday at 2pm"},
    ]
    assert detect_stage(messages) == VIEWING_BOOKED


# ── cross_006: outbound_count → _sender ────────────────────────────────────────
def test_outbound_count_reads_sender_key():
    """outbound_count must correctly identify tenant messages via the 'sender' key.
    If _sender stops reading 'sender' (e.g., uses a wrong key), all messages appear
    senderless and the count returns 0 instead of 2."""
    messages = [
        {"sender": "tenant",   "message": "Hi, I'm interested in the property"},
        {"sender": "tenant",   "message": "Are you available Thursday?"},
        {"sender": "landlord", "message": "Yes, Thursday works"},
    ]
    assert outbound_count(messages) == 2


# ── cross_007: phone_shared_state → tenant_shared_phone ─────────────────────────
def test_phone_shared_state_detects_tenant_sender():
    """phone_shared_state must detect when a 'tenant' sender has shared a phone number.
    If tenant_shared_phone excludes the 'tenant' sender from its scan, this returns False
    even though the number is plainly in the conversation."""
    messages = [
        {"sender": "tenant", "message": "My number is 07911123456"},
    ]
    persona = {"mobile_number": "07911123456"}
    assert phone_shared_state(messages, persona) is True
