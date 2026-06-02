import json

from scripts.analyze_corpus_number_capture import analyze_corpus
from scripts.ingest_corpus import (
    contains_phone_literal,
    parse_corpus,
    redact_phones,
)


def test_parse_corpus_and_redact_phone_literals(tmp_path):
    corpus = tmp_path / "full-conversations.md"
    corpus.write_text(
        """## Conversation 1
Source: https://www.openrent.co.uk/messages/1

Tenant: "Hi, could we arrange a viewing?"

Landlord: "Yes, call me on +44 7743 722832."

""",
        encoding="utf-8",
    )

    conversations = parse_corpus(corpus)
    assert len(conversations) == 1
    assert conversations[0]["turns"][0]["speaker"] == "Tenant"

    redacted = redact_phones(corpus.read_text(encoding="utf-8"))
    assert "[PHONE_REDACTED]" in redacted
    assert not contains_phone_literal(redacted)


def test_analyze_corpus_number_capture_labels_before_redaction(tmp_path):
    corpus = tmp_path / "full-conversations.md"
    corpus.write_text(
        """## Conversation 1
Source: https://www.openrent.co.uk/messages/1

Tenant: "Hi, could we arrange a viewing?"

Landlord: "Tomorrow evening works."

Tenant: "We'll be driving down, could you send the best number in case we're delayed?"

Landlord: "No problem, +44 7743 722832."

## Conversation 2
Source: https://www.openrent.co.uk/messages/2

Tenant: "Hi, could we arrange a viewing?"

Landlord: "Sorry, it is now rented."

""",
        encoding="utf-8",
    )

    report = analyze_corpus(corpus)
    serialized = json.dumps(report)

    assert report["total_conversations"] == 2
    assert report["successful_conversations"] == 1
    assert len(report["examples"]) == 1
    assert report["examples"][0]["features"]["used_travel_context"] is True
    assert report["examples"][0]["features"]["used_logistics_context"] is True
    assert "[PHONE_REDACTED]" in report["examples"][0]["landlord_phone_turn"]
    assert not contains_phone_literal(serialized)
