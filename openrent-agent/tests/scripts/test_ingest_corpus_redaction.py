"""Apparatus precondition A1 + P1.1 predicate 2 (single test):

Every phone-pattern variant observed in full-conversations.md must
be replaced by the [PHONE_REDACTED] token. A final regex sweep
across the redacted output must find ZERO literal phones.

Precommit: hippocampus-1:docs/OPENRENT-POSTCLOSURE-CORPUS-PROBE-PRECOMMIT.md
"""

from __future__ import annotations

from scripts.ingest_corpus import (
    contains_phone_literal,
    redact_phones,
)


# The five phone-pattern variants observed in the corpus, plus
# negative samples that must NOT be redacted.
_PHONE_SAMPLES = [
    "Call me on 07843 123456",
    "My number is 447857488662",
    "07848 083338",
    "+44 7743 722832 this is my husbands number",
    "Here is my contact: (Number Removed)",
    "(Phone Removed) please call",
    "Call 07848083338 today",
    "+44 7848 083 338",
]

_NEGATIVE_SAMPLES = [
    "We make about 90000 as combined salary",  # 5 digits, NOT a phone
    "for 2 years",  # 1 digit
    "on Monday 6:00/30pm",  # short numbers + colon
    "100% sure",  # short digit run
    "Code 12345",  # 5 digits
]


def test_all_observed_phone_patterns_are_redacted():
    for sample in _PHONE_SAMPLES:
        redacted = redact_phones(sample)
        assert "[PHONE_REDACTED]" in redacted, (
            f"redaction missed token for: {sample!r} -> {redacted!r}"
        )
        assert not contains_phone_literal(redacted), (
            f"literal phone survived redaction in: {sample!r} -> {redacted!r}"
        )


def test_short_digit_runs_are_not_overredacted():
    for sample in _NEGATIVE_SAMPLES:
        redacted = redact_phones(sample)
        assert "[PHONE_REDACTED]" not in redacted, (
            f"false-positive redaction in: {sample!r} -> {redacted!r}"
        )


def test_redaction_is_idempotent():
    sample = "Call me on +44 7743 722832 or 07848 083338, (Number Removed) too."
    once = redact_phones(sample)
    twice = redact_phones(once)
    assert once == twice
    assert not contains_phone_literal(twice)


def test_corpus_sweep_post_redaction_finds_zero_phones():
    """End-to-end apparatus check: redact the entire corpus FILE text
    (the same order ingest_corpus.py uses, so cross-turn digit-runs
    like '07419'\\n'833395' are caught upstream), then sweep for any
    surviving literal phone match. Strict P1.1 predicate 2 condition.
    """

    from pathlib import Path

    corpus_path = Path("D:/openrent/openrent/full-conversations.md")
    if not corpus_path.is_file():
        import pytest

        pytest.skip(f"corpus not present at {corpus_path}; skip sweep")

    raw = corpus_path.read_text(encoding="utf-8")
    redacted = redact_phones(raw)
    assert not contains_phone_literal(redacted), (
        "P1.1 predicate 2 FAILED: literal phone survived corpus-wide redaction"
    )
