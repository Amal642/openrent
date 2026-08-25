"""Tests for robust viewing-time handling: UTC storage, UK display, relative-date
anchoring, and en-route reconciliation."""
from datetime import datetime
from app.utils.scheduling import uk_naive_to_utc_naive, utc_naive_to_uk_naive
from app.ai.stages import (
    message_uk_timestamp_str,
    landlord_says_en_route,
    reconcile_viewing_datetime,
)


# ---- timezone canonicalisation (BST vs GMT) --------------------------------
def test_bst_uk_to_utc_is_minus_one_hour():
    # 21 Aug is BST (UTC+1): 13:00 UK -> 12:00 UTC
    assert uk_naive_to_utc_naive(datetime(2026, 8, 21, 13, 0)) == datetime(2026, 8, 21, 12, 0)


def test_gmt_uk_to_utc_is_same():
    # 21 Jan is GMT (UTC+0): 13:00 UK -> 13:00 UTC
    assert uk_naive_to_utc_naive(datetime(2026, 1, 21, 13, 0)) == datetime(2026, 1, 21, 13, 0)


def test_roundtrip_bst():
    dt = datetime(2026, 8, 21, 13, 0)
    assert utc_naive_to_uk_naive(uk_naive_to_utc_naive(dt)) == dt


def test_none_passthrough():
    assert uk_naive_to_utc_naive(None) is None
    assert utc_naive_to_uk_naive(None) is None


# ---- per-message UK timestamp string ---------------------------------------
def test_message_uk_timestamp_str_bst():
    # 06:36 UTC on 21 Aug -> 07:36 UK
    m = {"sender": "us", "message": "hi", "timestamp": "2026-08-21T06:36:00+00:00"}
    s = message_uk_timestamp_str(m)
    assert s and "07:36" in s and "21 Aug" in s


def test_message_uk_timestamp_str_missing():
    assert message_uk_timestamp_str({"sender": "landlord", "message": "hi"}) is None


# ---- en-route detection -----------------------------------------------------
def _ll(t):
    return {"sender": "landlord", "message": t}


def test_en_route_running_late():
    assert landlord_says_en_route([_ll("Running 5-10min")])
    assert landlord_says_en_route([_ll("More like 5 min late")])
    assert landlord_says_en_route([_ll("On my way, see you shortly")])


def test_en_route_ignores_our_own():
    assert not landlord_says_en_route([{"sender": "us", "message": "on my way"}])


def test_en_route_uses_latest_inbound():
    msgs = [_ll("running late"), {"sender": "us", "message": "ok"}, _ll("what is the address?")]
    assert not landlord_says_en_route(msgs)  # latest inbound is not en-route


def test_ordinary_message_not_en_route():
    assert not landlord_says_en_route([_ll("Friday at 1pm works, see you then")])


# ---- reconciliation (UK-local): the 45969788 off-by-one-day bug ------------
from app.ai.stages import resolve_viewing_datetime, parse_llm_viewing_datetime


def _ll_ts(text, ts):
    return {"sender": "landlord", "message": text, "timestamp": ts}


def test_reconcile_snaps_drifted_date_to_today_uk():
    # Resolver/LLM drifted to 22 Aug 13:00 (UK); en-route msg sent 21 Aug.
    drifted_uk = datetime(2026, 8, 22, 13, 0)
    msgs = [_ll_ts("Running 5-10min", "2026-08-21T11:58:00+00:00")]
    fixed = reconcile_viewing_datetime(drifted_uk, msgs)
    assert fixed == datetime(2026, 8, 21, 13, 0)  # snapped to today, UK clock kept


def test_reconcile_noop_when_same_day_uk():
    same = datetime(2026, 8, 21, 13, 0)
    msgs = [_ll_ts("running late", "2026-08-21T11:58:00+00:00")]
    assert reconcile_viewing_datetime(same, msgs) == same


def test_reconcile_noop_without_en_route_uk():
    drifted = datetime(2026, 8, 22, 13, 0)
    msgs = [_ll_ts("see you Friday at 1pm", "2026-08-21T11:58:00+00:00")]
    assert reconcile_viewing_datetime(drifted, msgs) == drifted


# ---- single resolver: deterministic wins over LLM arithmetic ---------------
def _det_thread():
    # Landlord + our side agree "1pm", last explicit mention is same-day.
    return [
        {"sender": "landlord", "message": "1pm tomorrow will be fine", "timestamp": "2026-08-20T08:51:00+00:00"},
        {"sender": "us", "message": "That works, thanks", "timestamp": "2026-08-20T08:51:00+00:00"},
        {"sender": "us", "message": "I'll be there at 1pm. See you soon.", "timestamp": "2026-08-21T11:58:00+00:00"},
    ]


def test_resolver_prefers_deterministic_over_wrong_llm_date():
    msgs = _det_thread()
    # LLM wrongly says 22 Aug; deterministic anchors the last "1pm" to 21 Aug.
    llm = {"viewing_datetime": "2026-08-22 13:00"}
    resolved = resolve_viewing_datetime(msgs, llm_detection=llm, now=datetime(2026, 8, 21, 12, 0))
    assert resolved == datetime(2026, 8, 21, 13, 0)


def test_resolver_falls_back_to_llm_when_deterministic_none():
    # Bare-hour phrasing the deterministic parser rejects -> LLM gap-fills.
    msgs = [{"sender": "landlord", "message": "Viewing booked for tomorrow at 3.", "timestamp": "2026-08-21T09:00:00+00:00"}]
    llm = {"viewing_datetime": "2026-08-22 15:00"}
    resolved = resolve_viewing_datetime(msgs, llm_detection=llm, now=datetime(2026, 8, 21, 9, 0))
    assert resolved == datetime(2026, 8, 22, 15, 0)


def test_resolver_drops_out_of_bounds_llm_only():
    msgs = [{"sender": "landlord", "message": "Viewing booked for tomorrow at 3.", "timestamp": "2026-08-21T09:00:00+00:00"}]
    llm = {"viewing_datetime": "2027-12-01 15:00"}  # ~15 months out -> out of bounds
    resolved = resolve_viewing_datetime(msgs, llm_detection=llm, now=datetime(2026, 8, 21, 9, 0))
    assert resolved is None


def test_resolver_none_when_nothing():
    msgs = [{"sender": "landlord", "message": "what is your budget?", "timestamp": "2026-08-21T09:00:00+00:00"}]
    assert resolve_viewing_datetime(msgs, llm_detection={"viewing_datetime": None}, now=datetime(2026, 8, 21, 9, 0)) is None


def test_parse_llm_viewing_datetime_formats():
    assert parse_llm_viewing_datetime("2026-08-21 13:00") == datetime(2026, 8, 21, 13, 0)
    assert parse_llm_viewing_datetime("2026-08-21T13:00") == datetime(2026, 8, 21, 13, 0)
    assert parse_llm_viewing_datetime(None) is None
    assert parse_llm_viewing_datetime("garbage") is None


# ---- outbound stale relative-date guard (#2) --------------------------------
from app.ai.stages import correct_stale_viewing_day
from app.utils.scheduling import uk_naive_to_utc_naive as _u


def test_stale_tomorrow_rewritten_to_today():
    # Viewing today 13:00; reply wrongly says "1pm tomorrow".
    viewing = _u(datetime(2026, 8, 21, 13, 0))
    now = datetime(2026, 8, 21, 8, 0)  # a UK-ish 'now'; guard converts internally
    out = correct_stale_viewing_day("I'll be there at 1pm tomorrow. See you then.", viewing, now=_u(now))
    assert out == "I'll be there at 1pm today. See you then."


def test_correct_tomorrow_left_alone():
    # Viewing genuinely tomorrow; "1pm tomorrow" is correct -> unchanged.
    viewing = _u(datetime(2026, 8, 22, 13, 0))
    now = _u(datetime(2026, 8, 21, 8, 0))
    out = correct_stale_viewing_day("Great, see you at 1pm tomorrow.", viewing, now=now)
    assert out == "Great, see you at 1pm tomorrow."


def test_alternative_offer_not_touched():
    # "also ... tomorrow" is an alternative, not the agreed slot -> unchanged.
    viewing = _u(datetime(2026, 8, 21, 13, 0))
    now = _u(datetime(2026, 8, 21, 8, 0))
    txt = "1pm works, though I could also do tomorrow if easier."
    assert correct_stale_viewing_day(txt, viewing, now=now) == txt


def test_different_time_reschedule_not_touched():
    # Reply proposes a DIFFERENT time (3pm) -> agreed time (1pm) not present -> skip.
    viewing = _u(datetime(2026, 8, 21, 13, 0))
    now = _u(datetime(2026, 8, 21, 8, 0))
    txt = "Could we do 3pm tomorrow?"
    assert correct_stale_viewing_day(txt, viewing, now=now) == txt


def test_no_time_restated_not_touched():
    # No agreed clock time in the reply -> conservative no-op.
    viewing = _u(datetime(2026, 8, 21, 13, 0))
    now = _u(datetime(2026, 8, 21, 8, 0))
    txt = "See you tomorrow!"
    assert correct_stale_viewing_day(txt, viewing, now=now) == txt


def test_far_future_viewing_not_touched():
    viewing = _u(datetime(2026, 8, 25, 13, 0))  # 4 days out
    now = _u(datetime(2026, 8, 21, 8, 0))
    txt = "See you at 1pm tomorrow."
    assert correct_stale_viewing_day(txt, viewing, now=now) == txt


def test_no_viewing_datetime_noop():
    assert correct_stale_viewing_day("at 1pm tomorrow", None) == "at 1pm tomorrow"


def test_day_after_tomorrow_rewritten():
    viewing = _u(datetime(2026, 8, 21, 13, 0))  # today
    now = _u(datetime(2026, 8, 21, 8, 0))
    out = correct_stale_viewing_day("I'll come at 1pm day after tomorrow.", viewing, now=now)
    assert out == "I'll come at 1pm today."
