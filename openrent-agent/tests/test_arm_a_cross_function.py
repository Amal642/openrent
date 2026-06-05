"""
ARM_A cross-function calibration test suite — 20 cases where the fix is in a helper,
not in the high-level function the test calls.

Each case design:
  - Test calls function A (high-level)
  - Bug is seeded in function B (helper/dependency called by A)
  - ARM_A context = function A's source only → cannot locate bug
  - Demonstrates where cross-function retrieval adds value

Original 7 (cross_001–cross_007):
  cross_001: detect_stage                    → _recent_messages        (stages.py)
  cross_002: detect_landlord_attitude        → landlord_messages        (conversation_memory.py)
  cross_003: latest_landlord_asked_for_phone → landlord_asked_for_phone (personas.py)
  cross_004: viewing_requested               → _content                 (conversation_memory.py)
  cross_005: detect_stage                    → _matches_any             (stages.py)
  cross_006: outbound_count                  → _sender                  (conversation_memory.py)
  cross_007: phone_shared_state              → tenant_shared_phone       (personas.py)

OPEN-53 expansion (cross_008–cross_020):
  cross_008: detect_stage                    → _message_text            (stages.py)           name-hidden
  cross_009: detect_stage                    → _has_time                (stages.py)           name-hidden
  cross_010: extract_viewing_datetime        → _target_date_from_text   (stages.py)           name-hidden
  cross_011: extract_viewing_datetime        → _date_spans              (stages.py)           name-hidden
  cross_012: get_conversation_style          → normalize_conversation_style (personas.py)     name-hidden
  cross_013: should_share_phone_now          → normalize_conversation_style (personas.py)     name-hidden
  cross_014: detect_landlord_attitude        → _content                 (conversation_memory.py) name-visible
  cross_015: detect_landlord_attitude        → _sender                  (conversation_memory.py) name-visible, depth-2
  cross_016: phone_shared_state              → tenant_shared_phone       (personas.py)        name-visible
  cross_017: outbound_count                  → _sender                  (conversation_memory.py) name-visible
  cross_018: extract_viewing_datetime        → _overlaps_any            (stages.py)           name-visible
  cross_019: detect_stage                    → _matches_any             (stages.py)           name-visible
  cross_020: landlord_messages               → _sender                  (conversation_memory.py) name-visible

All tests assert CORRECT behaviour and must PASS on the current codebase.
"""

from datetime import datetime

from app.ai.conversation_memory import (
    detect_landlord_attitude,
    landlord_messages,
    latest_landlord_asked_for_phone,
    outbound_count,
    phone_shared_state,
    viewing_requested,
)
from app.ai.personas import (
    get_conversation_style,
    should_share_phone_now,
)
from app.ai.stages import detect_stage, extract_viewing_datetime
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


# ── OPEN-53 expansion: cross_008–cross_020 ─────────────────────────────────────
# name-hidden seeds (B name absent from test docstring and assertion)
# name-visible seeds (B name present in test docstring)
# See OPEN-52/53 in PROJECT-GUIDE.md for localizer benchmark results.

# ── cross_008: detect_stage → _message_text (name-hidden) ─────────────────────
def test_detect_stage_booking_in_message_field():
    """A confirmed booking in the latest message must return VIEWING_BOOKED.
    The booking keyword is stored under the 'message' key; if the wrong field
    is read, the text is empty and the booking is invisible to detect_stage."""
    messages = [
        {"sender": "landlord", "message": "Are you free this week?"},
        {"sender": "tenant",   "message": "Yes, any day works"},
        {"sender": "landlord", "message": "Confirmed, see you Friday at 3pm"},
    ]
    assert detect_stage(messages) == VIEWING_BOOKED


# ── cross_009: detect_stage → _has_time (name-hidden) ─────────────────────────
def test_detect_stage_booking_requires_time_confirmation():
    """A booking confirmation spread across messages must yield VIEWING_BOOKED
    only when time information is present. The stage logic uses a time-presence
    check to confirm the booking; without it the combined context is ambiguous."""
    messages = [
        {"sender": "landlord", "message": "Confirmed, I'll see you then"},
        {"sender": "tenant",   "message": "Perfect, see you Saturday at 2pm"},
        {"sender": "landlord", "message": "Great"},
    ]
    assert detect_stage(messages) == VIEWING_BOOKED


# ── cross_010: extract_viewing_datetime → _target_date_from_text (name-hidden) ─
def test_extract_viewing_datetime_tomorrow_resolves_to_next_day():
    """'Tomorrow at 3pm' must resolve to tomorrow's calendar date, not today.
    The date resolution uses a keyword check; if the keyword is missed,
    the date defaults to today regardless of what the message says."""
    now = datetime(2026, 6, 10, 14, 0)
    messages = [{"sender": "landlord", "message": "see you tomorrow at 3pm"}]
    result = extract_viewing_datetime(messages, now=now)
    assert result is not None
    assert result.date().day == 11  # tomorrow = June 11


# ── cross_011: extract_viewing_datetime → _date_spans (name-hidden) ───────────
def test_extract_viewing_datetime_time_without_date():
    """A message with only a time and no numeric date must yield a valid datetime.
    When no date spans are found, time candidates should not be filtered out.
    If date-span detection is wrong, even clean time strings are discarded."""
    now = datetime(2026, 6, 10, 14, 0)
    messages = [{"sender": "landlord", "message": "let's meet at 3pm"}]
    result = extract_viewing_datetime(messages, now=now)
    assert result is not None
    assert result.hour == 15


# ── cross_012: get_conversation_style → normalize_conversation_style (name-hidden)
def test_get_conversation_style_resolves_alias():
    """get_conversation_style with an aliased style name must return the resolved
    canonical style config. If alias resolution is broken, an unknown key reaches
    CONVERSATION_STYLES and a KeyError is raised."""
    style = get_conversation_style("friendly_couple")
    assert style["phone_fetching_type"] == "delayed"


# ── cross_013: should_share_phone_now → normalize_conversation_style (name-hidden)
def test_should_share_phone_respects_immediate_style_alias():
    """With phone_fetching_type=delayed but conversation_style resolving to an
    immediate-type alias, should_share_phone_now must account for the resolved
    style. If alias resolution is skipped, the conservative delayed path is
    taken and the function incorrectly returns False."""
    persona = {
        "mobile_number": "07911123456",
        "phone_fetching_type": "delayed",
        "conversation_style": "direct_professional",
    }
    result = should_share_phone_now(
        persona,
        landlord_asked=False,
        phone_shared=False,
        outbound_count=1,
        stage=None,
    )
    assert result is True


# ── cross_014: detect_landlord_attitude → _content (name-visible) ─────────────
def test_detect_landlord_attitude_aggressive_from_message_field():
    """detect_landlord_attitude must read message text via _content; if _content
    returns empty string (wrong key), pattern matching finds nothing and the
    function defaults to 'responsive' even for aggressive landlord messages."""
    messages = [
        {"sender": "inbound", "message": "stop wasting my time, serious enquiries only"},
    ]
    assert detect_landlord_attitude(messages) == "aggressive"


# ── cross_015: detect_landlord_attitude → _sender (name-visible, depth-2) ─────
def test_detect_landlord_attitude_sender_case_sensitivity():
    """detect_landlord_attitude relies on _sender returning lowercase sender
    values so landlord_messages can filter correctly. If _sender returns uppercase
    values instead, the case-sensitive set membership check fails and no landlord
    messages are returned, causing the attitude to default to 'responsive'."""
    messages = [
        {"sender": "landlord", "message": "stop wasting my time, serious only"},
    ]
    assert detect_landlord_attitude(messages) == "aggressive"


# ── cross_016: phone_shared_state → tenant_shared_phone (name-visible) ─────────
def test_phone_shared_state_digit_extraction():
    """phone_shared_state must find the phone number digits within message text.
    tenant_shared_phone strips non-digits to compare; if it strips digits instead,
    the phone number is never found even when plainly present in the message."""
    messages = [
        {"sender": "tenant", "message": "My number is 07911123456"},
    ]
    persona = {"mobile_number": "07911123456"}
    assert phone_shared_state(messages, persona) is True


# ── cross_017: outbound_count → _sender (name-visible) ────────────────────────
def test_outbound_count_case_insensitive_sender():
    """outbound_count relies on _sender returning lowercase sender values so the
    set membership check matches correctly. If _sender returns uppercase, 'TENANT'
    and 'OUTBOUND' are not in the lowercase set and messages go uncounted."""
    messages = [
        {"sender": "tenant",   "message": "Hi, interested in the flat"},
        {"sender": "outbound", "message": "Following up on the viewing"},
        {"sender": "landlord", "message": "Yes please come round"},
    ]
    assert outbound_count(messages) == 2


# ── cross_018: extract_viewing_datetime → _overlaps_any (name-visible) ─────────
def test_extract_viewing_datetime_time_not_excluded_when_no_dates():
    """extract_viewing_datetime must not exclude time candidates when there are
    no date spans in the message. _overlaps_any must return False for an empty
    span list; if it incorrectly returns True, all time candidates are filtered
    out and the function returns None instead of a valid datetime."""
    now = datetime(2026, 6, 10, 14, 0)
    messages = [{"sender": "landlord", "message": "Confirmed, meet at 4pm"}]
    result = extract_viewing_datetime(messages, now=now)
    assert result is not None


# ── cross_019: detect_stage → _matches_any (name-visible) ─────────────────────
def test_detect_stage_reschedule_mid_sentence():
    """detect_stage must detect rescheduling intent when the keyword appears
    mid-sentence, not just at the start. _matches_any uses re.search; if it
    switches to re.match, patterns are only checked at the start of the string
    and mid-sentence keywords like 'reschedule' go undetected."""
    messages = [
        {"sender": "tenant", "message": "I need to reschedule our appointment."},
    ]
    assert detect_stage(messages) == VIEWING_DISCUSSION


# ── cross_020: landlord_messages → _sender (name-visible) ─────────────────────
def test_landlord_messages_reads_direction_key():
    """landlord_messages must include messages where the 'direction' key holds
    'inbound' when no 'sender' key is present. If _sender drops the 'direction'
    fallback, OpenRent-format messages with only a 'direction' field are excluded."""
    messages = [{"direction": "inbound", "message": "Hello, still interested?"}]
    assert landlord_messages(messages) == messages
