"""The pre-cancel number-ask must never contain a phone number of our own.

Regression for the fake-number hallucination (2026-08-15): the model sometimes
answered a landlord's "the number you gave doesn't work" by inventing a number
("Sure, it's 07123 456789"), handing the landlord a dead number that reads as a
scam. The generator now rejects any phone-number-shaped output and falls back to
a safe ask.
"""
from app.ai.replies import (
    _contains_phone_number,
    _pre_cancel_number_ask_fallback,
    _PRE_CANCEL_NUMBER_ASK_FALLBACKS,
)


def test_detects_fabricated_number():
    assert _contains_phone_number("Sure, it's 07123 456789, feel free to call or text.") is True


def test_detects_various_number_shapes():
    assert _contains_phone_number("07123456789") is True
    assert _contains_phone_number("+44 7911 123456") is True
    assert _contains_phone_number("call me on 07700 900123 anytime") is True


def test_clean_ask_is_not_flagged():
    assert _contains_phone_number("Could I grab your number for the day in case I get delayed?") is False


def test_short_numbers_not_flagged():
    # times/dates must not trip the guard
    assert _contains_phone_number("See you at 2pm on the 16th, flat 52") is False


def test_empty_is_safe():
    assert _contains_phone_number("") is False
    assert _contains_phone_number(None) is False


def test_all_fallbacks_are_clean_asks():
    for msg in _PRE_CANCEL_NUMBER_ASK_FALLBACKS:
        assert not _contains_phone_number(msg)
        assert "?" in msg  # it asks


def test_fallback_is_deterministic_and_valid():
    out = _pre_cancel_number_ask_fallback("some conversation text")
    assert out in _PRE_CANCEL_NUMBER_ASK_FALLBACKS
