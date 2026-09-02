"""Viewing-datetime day resolution: ordinal+month parsing, cross-message
day-carry, and grounded-vs-guessed day handling in resolve_viewing_datetime.

Regression cover for the free-text day-collapse bug (thread 46215267: day named
in an earlier turn, only a bare time in the confirming message -> stored a day
early) while preserving the 45969788 fix (a grounded deterministic day must
still beat the LLM's arithmetic).
"""
from datetime import datetime, timedelta

from app.ai.stages import (
    extract_viewing_datetime,
    _extract_viewing_datetime_impl,
    resolve_viewing_datetime,
    _explicit_target_date,
    _resolve_day_month,
)

NOW = datetime(2026, 9, 1, 10, 0)  # Tuesday 1 Sep, naive UTC/UK (BST offset irrelevant here)


def _m(sender, text, ts=NOW):
    return {"sender": sender, "message": text,
            "timestamp": ts.strftime("%Y-%m-%dT%H:%M:%S")}


# --- ordinal + month-name parsing -------------------------------------------

def test_resolve_day_month_ordinal_then_month():
    assert _resolve_day_month("come on the 3rd september", NOW) == datetime(2026, 9, 3).date()


def test_resolve_day_month_month_then_day():
    assert _resolve_day_month("see you september 3rd", NOW) == datetime(2026, 9, 3).date()


def test_resolve_day_month_abbreviated():
    assert _resolve_day_month("the 3rd sept works", NOW) == datetime(2026, 9, 3).date()


def test_resolve_day_month_rolls_to_next_year_when_clearly_past():
    # In Sep, "3rd January" means next January.
    assert _resolve_day_month("the 3rd january", NOW) == datetime(2027, 1, 3).date()


def test_resolve_day_month_none_when_no_month():
    assert _resolve_day_month("the 3rd works for me", NOW) is None


def test_extract_ordinal_month_in_confirming_message():
    msgs = [_m("landlord", "Confirmed for the 3rd September at 8:30am.")]
    dt, grounded = _extract_viewing_datetime_impl(msgs, NOW)
    assert dt == datetime(2026, 9, 3, 8, 30)
    assert grounded is True


def test_extract_month_day_at_5pm():
    msgs = [_m("landlord", "See you September 3rd at 5pm.")]
    assert extract_viewing_datetime(msgs, NOW) == datetime(2026, 9, 3, 17, 0)


# --- cross-message day carry -------------------------------------------------

def test_day_carry_from_earlier_turn():
    # Day pinned earlier ("3rd September"); confirming line has only the time.
    msgs = [
        _m("landlord", "Let's do the viewing on the 3rd September.", NOW),
        _m("us", "Great, what time suits you?", NOW),
        _m("landlord", "See you at 8:30.", NOW),  # bare time, booked keyword, no day
    ]
    dt, grounded = _extract_viewing_datetime_impl(msgs, NOW)
    assert dt == datetime(2026, 9, 3, 8, 30)
    assert grounded is True  # grounded via carry


def test_day_carry_weekday_from_earlier_turn():
    msgs = [
        _m("landlord", "Are you free Thursday for a viewing?", NOW),
        _m("us", "Yes, what time?", NOW),
        _m("landlord", "See you at 6pm then.", NOW),  # no day in this line
    ]
    dt, grounded = _extract_viewing_datetime_impl(msgs, NOW)
    assert dt == datetime(2026, 9, 3, 18, 0)  # Thu 3 Sep
    assert grounded is True


def test_no_day_anywhere_is_ungrounded():
    msgs = [_m("landlord", "See you at 3pm.", NOW)]  # no day in the whole thread
    dt, grounded = _extract_viewing_datetime_impl(msgs, NOW)
    assert dt == datetime(2026, 9, 1, 15, 0)  # falls back to message date
    assert grounded is False


def test_two_weekdays_is_ambiguous_ungrounded():
    msgs = [_m("landlord", "Happy to view Friday or Saturday at 3pm.", NOW)]
    dt, grounded = _extract_viewing_datetime_impl(msgs, NOW)
    assert grounded is False  # ambiguous day -> deferred to the LLM in resolve
    assert _explicit_target_date("friday or saturday at 3pm", NOW) is None


# --- resolve: grounded vs guessed day ---------------------------------------

def test_resolve_prefers_llm_day_when_deterministic_ungrounded():
    # Bare time, no day anywhere -> deterministic day is a guess -> use LLM's day.
    msgs = [_m("landlord", "See you at 3pm.", NOW)]  # det -> Tue 1 Sep 15:00 (guess)
    llm = {"viewing_datetime": "2026-09-03 15:00"}   # LLM read Thursday from context
    chosen = resolve_viewing_datetime(msgs, llm_detection=llm, now=NOW)
    assert chosen == datetime(2026, 9, 3, 15, 0)     # LLM day, deterministic time


def test_resolve_keeps_grounded_deterministic_day_over_llm():
    # Explicit weekday -> grounded -> deterministic day beats LLM arithmetic (45969788).
    msgs = [_m("landlord", "See you Thursday at 3pm.", NOW)]  # det -> Thu 3 Sep 15:00
    llm = {"viewing_datetime": "2026-09-02 15:00"}            # LLM wrongly says Wed
    chosen = resolve_viewing_datetime(msgs, llm_detection=llm, now=NOW)
    assert chosen == datetime(2026, 9, 3, 15, 0)


def test_resolve_carry_grounded_day_beats_llm():
    # Day carried from earlier turn is grounded -> beats a conflicting LLM day.
    msgs = [
        _m("landlord", "Let's view on the 3rd September.", NOW),
        _m("landlord", "See you at 8:30.", NOW),
    ]
    llm = {"viewing_datetime": "2026-09-02 08:30"}  # LLM wrongly says the 2nd
    chosen = resolve_viewing_datetime(msgs, llm_detection=llm, now=NOW)
    assert chosen.date() == datetime(2026, 9, 3).date()


def test_resolve_same_day_takes_llm_time():
    # Grounded day, but the agreed time differs -> LLM time on the anchored day.
    msgs = [_m("landlord", "See you Thursday, let's say 8:30.", NOW)]
    llm = {"viewing_datetime": "2026-09-03 09:00"}
    chosen = resolve_viewing_datetime(msgs, llm_detection=llm, now=NOW)
    assert chosen == datetime(2026, 9, 3, 9, 0)


def test_tomorrow_beside_weekday_is_ambiguous():
    # "6pm on Thursday ... message tomorrow" — the 'tomorrow' is logistics, not
    # the viewing day; the two conflicting days make this line ambiguous.
    assert _explicit_target_date(
        "i confirm 6pm on thursday, will message tomorrow", NOW
    ) is None


def test_time_range_beside_weekday_is_ambiguous():
    # "12-2 pm" can look like a 12/2 date; with a weekday present -> ambiguous.
    assert _explicit_target_date("would thursday lunch work? around 12-2 pm", NOW) is None


def test_availability_date_beside_viewing_weekday_is_ambiguous():
    assert _explicit_target_date(
        "available 1 october; could you view thursday after 6pm?", NOW
    ) is None


def test_thread_46217218_tomorrow_vs_weekday_resolves_via_carry():
    # Real failure: confirming line has both 'Thursday' and an unrelated
    # 'tomorrow' -> ambiguous -> carry the clean 'Thursday' from the prior turn.
    msgs = [
        _m("landlord", "Would you be available for a viewing on Thursday after 6pm?", NOW),
        _m("us", "Thursday after 6pm works for me. What time exactly?", NOW),
        _m("landlord",
           "I confirm 6pm on Thursday. I'll follow up with logistics over WhatsApp "
           "later (probably tomorrow).", NOW),
    ]
    dt, grounded = _extract_viewing_datetime_impl(msgs, NOW)
    assert dt == datetime(2026, 9, 3, 18, 0)  # Thursday, NOT Wednesday-from-"tomorrow"
    assert grounded is True


def test_thread_46215267_shape_end_to_end():
    # The real failure: day in an earlier turn, later turns only restate the time.
    msgs = [
        _m("landlord", "Are you interested to view on the 2nd or 3rd September?", NOW),
        _m("us", "Happy to come and see it on the 3rd September.", NOW),
        _m("landlord", "Are you available in the morning, 8 to 9 am?", NOW),
        _m("us", "How about 8.30 am on the 3rd? See you then.", NOW),
        _m("landlord", "8:30 would be fine.", NOW),
    ]
    chosen = resolve_viewing_datetime(
        msgs, llm_detection={"viewing_datetime": "2026-09-03 08:30"}, now=NOW
    )
    # The critical property: the DAY is the 3rd, never a day early.
    assert chosen.date() == datetime(2026, 9, 3).date()
