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
