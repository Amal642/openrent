"""A hyphenated time range ("6-6.30pm", "2-4pm") is not a dd-mm date.

Thread 46001652 (2026-08-21): "I'm available this evening from 6-6.30pm" was
read as 6 June, rolled to 2027, and stored as the viewing date, so the
pre-viewing cancellation could never fire."""
from datetime import datetime

import pytest

from app.ai.stages import resolve_viewing_datetime


def _resolve(*texts, at=datetime(2026, 10, 3, 9, 0)):
    msgs = [{"sender": "landlord", "message": t, "timestamp": at} for t in texts]
    msgs.append({"sender": "us", "message": "Great, see you then", "timestamp": at})
    return resolve_viewing_datetime(msgs, None, now=at)


def test_thread_46001652_evening_range_stays_on_the_day():
    at = datetime(2026, 8, 21, 8, 23)
    msgs = [
        {"sender": "landlord", "message": "Hello. Thanks for the interest. I'm available this evening from 6-6.30pm", "timestamp": at},
        {"sender": "landlord", "message": "Or anytime this weekend", "timestamp": at},
        {"sender": "us", "message": "I can do this evening at 6. That works well for us.", "timestamp": at},
    ]
    assert resolve_viewing_datetime(msgs, None, now=at).date() == datetime(2026, 8, 21).date()


@pytest.mark.parametrize("text, day", [
    ("Can you come Saturday 2-4pm?", 10),
    ("Tomorrow 6-7pm works", 4),
    ("Today between 5-6pm is fine", 3),
])
def test_time_ranges_are_not_dates(text, day):
    assert _resolve(text).date() == datetime(2026, 10, day).date()


@pytest.mark.parametrize("text", ["viewing on 12/10 at 3pm", "viewing on 12-10-2026 at 3pm"])
def test_real_numeric_dates_still_count(text):
    assert _resolve(text) == datetime(2026, 10, 12, 15, 0)


def test_two_named_dates_in_one_message_are_ambiguous():
    """Thread 45940966: 'tenanted until 2nd September ... viewings on 26th
    August'. Taking the first date (2 Sep) as certain would beat the LLM's
    correct 26 Aug; two dates must read as ambiguous instead."""
    from app.ai.stages import _explicit_target_date

    text = ("the property is presently tenanted until 2nd september. however, i have "
            "scheduled viewings with present tenants between 4:30-7:30pm on 26th august.")
    assert _explicit_target_date(text, datetime(2026, 8, 19, 10, 17)) is None
    assert _explicit_target_date("viewings on 26th august at 5pm", datetime(2026, 8, 19)) == datetime(2026, 8, 26).date()


@pytest.mark.parametrize("text, ref, expected", [
    # thread 46718887: "September 12:00" is a time, not 12 September
    ("viewing confirmed for saturday 26th september 12:00 pm at 92 hartford avenue",
     datetime(2026, 9, 22, 12, 38), datetime(2026, 9, 26)),
    # thread 46723624: "Sept 9-11am" is a time range, not 9 September
    ("for viewings, please share your availability on 26 sept 9-11am.",
     datetime(2026, 9, 22, 8, 16), datetime(2026, 9, 26)),
    # thread 45758272: the weekday pins the viewing date; the move-out date is not a rival
    ("viewing confirmed. visit 37 lichfield road on friday 14th august 2026 at 6.30 pm. "
     "current tenants are moving out of the property on 31st august 2026.",
     datetime(2026, 8, 11, 11, 52), datetime(2026, 8, 14)),
    # weekday + date further out than the next occurrence of that weekday
    ("can you do friday 21st august at 6pm?", datetime(2026, 8, 11, 9, 0), datetime(2026, 8, 21)),
])
def test_real_confirmations_resolve_to_the_stated_day(text, ref, expected):
    from app.ai.stages import _explicit_target_date

    assert _explicit_target_date(text, ref) == expected.date()


def test_weekday_beside_an_unrelated_date_is_still_ambiguous():
    from app.ai.stages import _explicit_target_date

    # 1 October 2026 IS a Thursday, but the weekday isn't written beside the
    # date, so the availability date and the viewing day stay rivals.
    assert _explicit_target_date("available 1 october; could you view thursday after 6pm?",
                                 datetime(2026, 9, 1)) is None
    assert _explicit_target_date("available 1 october; could you view friday after 6pm?",
                                 datetime(2026, 9, 1)) is None


def test_redacted_year_does_not_create_a_second_date():
    """Conversation 809: OpenRent turned '2026' into '2 (Number Removed) 0'; the
    '3rd July' month word must not also be read as 'July 2' (-> 2027-07-02)."""
    from app.ai.stages import _day_month_dates

    ref = datetime(2026, 6, 30, 10, 0)
    assert _day_month_dates("date: friday 3rd july 2 (number removed) 0", ref) == {datetime(2026, 7, 3).date()}
