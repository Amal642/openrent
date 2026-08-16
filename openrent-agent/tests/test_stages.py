from datetime import datetime

from app.ai.stages import detect_stage, extract_viewing_datetime
from app.db.status import VIEWING_BOOKED, VIEWING_DISCUSSION


def test_detect_stage_uses_recent_messages_over_old_booking():
    messages = [
        {"sender": "landlord", "message": "Confirmed, see you tomorrow at 7pm."},
        {"sender": "user", "message": "Great, see you then."},
        {"sender": "landlord", "message": "Actually can we rearrange for another time?"},
    ]

    assert detect_stage(messages) == VIEWING_DISCUSSION


def test_extract_viewing_datetime_uses_latest_booking_time():
    now = datetime(2026, 5, 19, 9, 0)
    messages = [
        {"sender": "landlord", "message": "I can do 5pm or 7pm tomorrow."},
        {"sender": "user", "message": "7pm works best for me."},
        {"sender": "landlord", "message": "Confirmed, see you tomorrow at 7pm."},
    ]

    viewing = extract_viewing_datetime(messages, now=now)

    assert viewing == datetime(2026, 5, 20, 19, 0)
    assert detect_stage(messages) == VIEWING_BOOKED


def test_extract_viewing_datetime_ignores_old_time_after_reschedule():
    now = datetime(2026, 5, 19, 9, 0)
    messages = [
        {"sender": "landlord", "message": "Confirmed, see you tomorrow at 6pm."},
        {"sender": "landlord", "message": "Can we reschedule? Thursday at 8pm works."},
        {"sender": "user", "message": "Thursday 8pm is fine."},
    ]

    viewing = extract_viewing_datetime(messages, now=now)

    assert viewing == datetime(2026, 5, 21, 20, 0)


def test_extract_viewing_datetime_anchors_to_message_time_not_processing_time():
    """A day-less time ("6:15pm") must resolve against WHEN the landlord sent it,
    not when the worker processes the thread. Regression for the Wardour/Tane
    thread that stored a viewing 2 days late because of processing lag."""
    messages = [
        {
            "sender": "landlord",
            "message": "Yes lets do the viewing, 6:15pm would be great if that works?",
            "timestamp": "2026-08-13T11:41:00+00:00",  # Thursday
        },
    ]

    # Worker runs two days later — must still be the 13th, not the 15th.
    viewing = extract_viewing_datetime(messages, now=datetime(2026, 8, 15, 14, 0))

    assert viewing == datetime(2026, 8, 13, 18, 15)


def test_extract_viewing_datetime_weekday_anchored_to_message_time():
    """A weekday ("Tuesday") must resolve to the Tuesday following the MESSAGE,
    not the next Tuesday after processing (which drifts a full week)."""
    messages = [
        {
            "sender": "landlord",
            "message": "See you Tuesday at 12:00 for the viewing.",
            "timestamp": "2026-08-08T13:00:00+00:00",  # Saturday
        },
    ]

    # Processed the following Wednesday — must be 08-11, not 08-18.
    viewing = extract_viewing_datetime(messages, now=datetime(2026, 8, 12, 9, 0))

    assert viewing == datetime(2026, 8, 11, 12, 0)


def test_extract_viewing_datetime_falls_back_to_now_without_timestamp():
    """No message timestamp -> anchor to `now` (prior behaviour preserved)."""
    messages = [
        {"sender": "landlord", "message": "See you Tuesday at 12:00 for the viewing."},
    ]

    viewing = extract_viewing_datetime(messages, now=datetime(2026, 8, 8, 13, 0))

    assert viewing == datetime(2026, 8, 11, 12, 0)


def test_extract_viewing_datetime_treats_bare_afternoon_hour_as_pm():
    now = datetime(2026, 6, 4, 17, 0)
    messages = [
        {"sender": "landlord", "message": "Viewing booked for tomorrow at 3."},
    ]

    viewing = extract_viewing_datetime(messages, now=now)

    assert viewing == datetime(2026, 6, 5, 15, 0)


def test_extract_viewing_datetime_uses_uk_numeric_date():
    now = datetime(2026, 6, 4, 9, 0)
    messages = [
        {"sender": "landlord", "message": "Confirmed for 05/06 at 3."},
    ]

    viewing = extract_viewing_datetime(messages, now=now)

    assert viewing == datetime(2026, 6, 5, 15, 0)


# SMOKE TEST — validates extractor/verifier pipeline only.
# This is one simple regex gap, not ARM_A evidence.
# ARM_A baseline requires 10-20 failures across distinct failure modes.
def test_detect_stage_implicit_reschedule_smoke():
    """Landlord says 'I may need to change it' after confirming — should revert to VIEWING_DISCUSSION."""
    messages = [
        {"sender": "landlord", "message": "Confirmed, see you Thursday at 2pm."},
        {"sender": "tenant", "message": "Perfect, looking forward to it."},
        {"sender": "landlord", "message": "I may need to change it, when are you free?"},
    ]
    assert detect_stage(messages) == VIEWING_DISCUSSION
