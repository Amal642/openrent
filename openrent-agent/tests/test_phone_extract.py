"""regex_extract_phone: single-message, correction, and split-across-messages.

The split cases are real audit losses (e.g. thread 45704829: "077144" + "36232").
The negative cases guard the stitching pass against fusing time/size digits into
a phantom number.
"""
from app.ai.extractors import regex_extract_phone


def test_single_message_number():
    assert regex_extract_phone(["My number is 07714436232"]) == "07714436232"


def test_split_across_two_messages():
    assert regex_extract_phone(["077144", "36232"]) == "07714436232"


def test_split_with_words_around_digits():
    assert (
        regex_extract_phone(["Hello Alex, to arrange viewing please call 07958", "354059. Cheers"])
        == "07958354059"
    )


def test_plus44_split():
    assert regex_extract_phone(["+44", "7714436232"]) == "+447714436232"


def test_correction_returns_latest_single_message_number():
    assert regex_extract_phone(["07111111111", "actually use 07222222222"]) == "07222222222"


def test_no_number_returns_none():
    assert regex_extract_phone(["Hi, when can you view?", "the flat is 32 SQM"]) is None


def test_time_and_size_digits_do_not_stitch_into_phantom():
    assert regex_extract_phone(["See you 6:30pm", "it is 32 sqm"]) is None


# --- 2026-09-30 audit: stop fusing unrelated numbers; accept real formats ---

def test_dates_rent_and_deposit_are_not_fused_into_a_phantom_number():
    # Old digit-stripping turned this into "07101450167" and saved it as a lead.
    assert regex_extract_phone(["available 07/10, rent 1450, deposit 1673"]) is None


def test_spaced_and_hyphenated_mobile_in_one_message():
    assert regex_extract_phone(["Sure, it's 07911 123 456 thanks"]) == "07911123456"
    assert regex_extract_phone(["call 07911-123-456"]) == "07911123456"


def test_plus44_with_trunk_zero_in_brackets():
    assert regex_extract_phone(["ring +44 (0)7700 900123 any time"]) == "+447700900123"


def test_plus44_followed_by_unrelated_digit_is_not_swallowed():
    # Old greedy \+44\d{10,12} produced "+4477009001236" (then rejected).
    assert regex_extract_phone(["+44 7700 900123, see you at 6"]) == "+447700900123"


def test_0044_prefix():
    assert regex_extract_phone(["0044 7911 123456"]) == "+447911123456"


def test_number_amid_other_numbers_in_same_message():
    msg = "Viewing Sat 12th at 2pm, flat 3, my number is 07714 436232, rent 1500"
    assert regex_extract_phone([msg]) == "07714436232"


def test_split_across_three_messages_with_pure_fragment_in_middle():
    assert regex_extract_phone(["my number 077", "144", "36232 thanks"]) == "07714436232"


def test_stitching_needs_the_number_to_cross_the_join():
    # Digits elsewhere in the messages must not be pulled into a join.
    assert regex_extract_phone(["Rent is 1450 and deposit 1673", "07/10 works"]) is None


def test_redacted_number_is_not_a_number():
    assert regex_extract_phone(["Sure - I'm (Number Removed) . See you later."]) is None
