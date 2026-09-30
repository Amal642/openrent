"""Unit tests for outbound-message dash scrubbing (AI-tell removal)."""
from app.utils.text import strip_ai_dashes


def test_em_dash_becomes_comma():
    assert strip_ai_dashes("Thanks \u2014 my husband\'s WhatsApp is 07599390221.") == (
        "Thanks, my husband\'s WhatsApp is 07599390221."
    )


def test_no_leading_space_before_comma():
    assert "  " not in strip_ai_dashes("A \u2014 B")
    assert strip_ai_dashes("A \u2014 B") == "A, B"


def test_em_dash_without_spaces():
    assert strip_ai_dashes("word\u2014word") == "word, word"


def test_en_dash_range_kept_as_hyphen():
    assert strip_ai_dashes("I can do 3\u20135pm") == "I can do 3-5pm"


def test_plain_text_unchanged():
    s = "Sure, my husband's WhatsApp is 07599390221. Best to reach him there."
    assert strip_ai_dashes(s) == s


def test_idempotent():
    once = strip_ai_dashes("Hi \u2014 there \u2013 5")
    assert strip_ai_dashes(once) == once


def test_none_and_empty_safe():
    assert strip_ai_dashes(None) is None
    assert strip_ai_dashes("") == ""


def test_actual_leaked_giveout_message_is_cleaned():
    leaked = ("Thanks \u2014 my husband\'s WhatsApp is 07599390221. "
              "He\'s handling the viewing coordination, so best to reach him there.")
    cleaned = strip_ai_dashes(leaked)
    assert "\u2014" not in cleaned
    assert cleaned.startswith("Thanks, my husband")


def test_em_dash_touching_a_number_gets_comma_and_space():
    # Live glitch 2026-09-30: "07783129181—best to message him" was sent as
    # "07783129181,best to message him".
    assert strip_ai_dashes("my partner's WhatsApp is 07783129181—best to message him") == (
        "my partner's WhatsApp is 07783129181, best to message him"
    )


def test_spaced_en_dash_is_a_clause_break_not_a_hyphen():
    assert strip_ai_dashes("Thursday works – see you then") == "Thursday works, see you then"
    assert strip_ai_dashes("I can do 3–5pm") == "I can do 3-5pm"


def test_reply_sanitiser_delegates_to_shared_scrubber():
    from app.ai.replies import _sanitize_dashes

    assert _sanitize_dashes("07783129181—best") == "07783129181, best"
    assert _sanitize_dashes("I can do 3–5pm") == "I can do 3-5pm"
    assert _sanitize_dashes("Thanks — see you") == strip_ai_dashes("Thanks — see you")
