"""Utilities for parsing and redacting the OpenRent conversation corpus."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


_PHONE_PATTERNS = (
    re.compile(r"\+?44\s?7\d{3}\s?\d{3,4}\s?\d{3,4}"),
    re.compile(r"\b07\d{3,4}\s?\d{3,4}\s?\d{3,4}\b"),
    re.compile(r"\b\d{10,11}\b"),
)
_REDACTED_MARKER = re.compile(r"\(\s*(?:Number|Phone)\s+Removed\s*\)", re.I)
_REDACT_TOKEN = "[PHONE_REDACTED]"

_CONVERSATION_HEADER_RX = re.compile(r"^## Conversation \d+", flags=re.M)
_SOURCE_RX = re.compile(r"^Source:\s*(\S+)\s*$", flags=re.M)
_TURN_RX = re.compile(r"^(Landlord|Tenant):\s*\"(.*?)\"\s*$", flags=re.M | re.S)


def redact_phones(text: str) -> str:
    """Replace observed phone formats and legacy markers with one stable token."""

    text = _REDACTED_MARKER.sub(_REDACT_TOKEN, text)
    for pattern in _PHONE_PATTERNS:
        text = pattern.sub(_REDACT_TOKEN, text)
    return text


def contains_phone_literal(text: str) -> bool:
    """Return True when raw phone-shaped text survives redaction."""

    return any(pattern.search(text) for pattern in _PHONE_PATTERNS)


def contains_phone_signal(text: str) -> bool:
    """Return True for either raw phone literals or OpenRent's removed marker."""

    return bool(_REDACTED_MARKER.search(text)) or contains_phone_literal(text)


def parse_corpus(path: str | Path) -> list[dict[str, Any]]:
    """Parse full-conversations.md into conversation dictionaries."""

    corpus_path = Path(path)
    text = corpus_path.read_text(encoding="utf-8")
    chunks = _CONVERSATION_HEADER_RX.split(text)[1:]
    conversations: list[dict[str, Any]] = []

    for index, chunk in enumerate(chunks, start=1):
        source_match = _SOURCE_RX.search(chunk)
        turns = [
            {"speaker": speaker, "text": message.strip()}
            for speaker, message in _TURN_RX.findall(chunk)
        ]
        conversations.append(
            {
                "id": index,
                "source": source_match.group(1) if source_match else "",
                "turns": turns,
            }
        )

    return conversations


def redact_conversation(conversation: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of a parsed conversation with message text redacted."""

    return {
        "id": conversation["id"],
        "source": conversation.get("source", ""),
        "turns": [
            {
                "speaker": turn["speaker"],
                "text": redact_phones(turn["text"]),
            }
            for turn in conversation.get("turns", [])
        ],
    }
