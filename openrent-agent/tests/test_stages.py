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
