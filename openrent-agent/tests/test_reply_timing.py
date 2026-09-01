"""Human reply-pacing gate (app/ai/reply_timing.py).

Guards that the conversational reply is held until a human-plausible delay has
passed since the landlord's REAL message time, while never blocking time-critical
(en-route) turns or turns whose real send time is unknown.
"""
from datetime import datetime, timedelta

from app.ai.reply_timing import (
    reply_hold_remaining_seconds,
    sample_human_delay_seconds,
    _latest_landlord_message,
)

NOW = datetime(2026, 9, 1, 12, 0, 0)  # fixed, naive UTC


def _msg(sender, text, ts=None):
    m = {"sender": sender, "message": text}
    if ts is not None:
        m["timestamp"] = ts.strftime("%Y-%m-%dT%H:%M:%S")
    return m


# --- delay sampler -----------------------------------------------------------

def test_sample_is_deterministic():
    a = sample_human_delay_seconds("46230796", "have scheduled for 3pm")
    b = sample_human_delay_seconds("46230796", "have scheduled for 3pm")
    assert a == b


def test_sample_varies_by_thread_and_message():
    a = sample_human_delay_seconds("111", "same text")
    b = sample_human_delay_seconds("222", "same text")
    c = sample_human_delay_seconds("111", "different text")
    assert a != b
    assert a != c


def test_sample_always_within_floor_and_ceiling():
    # Hard floor ~90s, ceiling 3h — never robotic-fast, never absurdly long.
    for i in range(2000):
        d = sample_human_delay_seconds(str(i), f"msg {i}")
        assert 90 <= d <= 3 * 60 * 60


# --- hold gate ---------------------------------------------------------------

def test_holds_when_reply_would_be_too_fast():
    # Landlord messaged 5s ago -> must not reply yet.
    msgs = [_msg("landlord", "have scheduled for 3pm", ts=NOW - timedelta(seconds=5))]
    assert reply_hold_remaining_seconds(msgs, "t1", now=NOW) > 0


def test_sends_once_enough_time_has_passed():
    # Same message but 4 hours old -> past any sampled delay (ceiling is 3h).
    msgs = [_msg("landlord", "have scheduled for 3pm", ts=NOW - timedelta(hours=4))]
    assert reply_hold_remaining_seconds(msgs, "t1", now=NOW) == 0.0


def test_no_timestamp_never_holds():
    # Cannot establish a real send time -> do not block the reply.
    msgs = [_msg("landlord", "have scheduled for 3pm", ts=None)]
    assert reply_hold_remaining_seconds(msgs, "t1", now=NOW) == 0.0


def test_en_route_bypasses_hold():
    # Imminent-coordination message: reply fast even though it just arrived.
    msgs = [_msg("landlord", "I'm on my way, running 5 min late", ts=NOW - timedelta(seconds=5))]
    assert reply_hold_remaining_seconds(msgs, "t1", now=NOW) == 0.0


def test_anchor_is_latest_landlord_message_not_our_reply():
    msgs = [
        _msg("landlord", "old landlord line", ts=NOW - timedelta(hours=5)),
        _msg("us", "our reply", ts=NOW - timedelta(hours=4)),
        _msg("landlord", "have scheduled for 3pm", ts=NOW - timedelta(seconds=5)),
    ]
    latest = _latest_landlord_message(msgs)
    assert latest["message"] == "have scheduled for 3pm"
    # Anchored on the fresh landlord line -> must hold.
    assert reply_hold_remaining_seconds(msgs, "t1", now=NOW) > 0


def test_outbound_direction_label_is_excluded():
    # DB-style rows use direction inbound/outbound rather than sender us/landlord.
    msgs = [
        {"direction": "inbound", "content": "hi", "timestamp": (NOW - timedelta(seconds=5)).strftime("%Y-%m-%dT%H:%M:%S")},
        {"direction": "outbound", "content": "our reply", "timestamp": (NOW - timedelta(seconds=2)).strftime("%Y-%m-%dT%H:%M:%S")},
    ]
    latest = _latest_landlord_message(msgs)
    assert latest["content"] == "hi"


def test_hold_decreases_as_time_passes():
    text = "have scheduled for 3pm"
    sent = NOW - timedelta(seconds=5)
    msgs = [_msg("landlord", text, ts=sent)]
    early = reply_hold_remaining_seconds(msgs, "t1", now=NOW)
    later = reply_hold_remaining_seconds(msgs, "t1", now=NOW + timedelta(minutes=1))
    assert later < early
