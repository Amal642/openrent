"""Analyze successful landlord-number capture patterns in the corpus."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.ingest_corpus import (
    contains_phone_literal,
    contains_phone_signal,
    parse_corpus,
    redact_phones,
)


_WHATSAPP_RX = re.compile(r"\bwhats\s*app\b|\bwhatsapp\b", re.I)
_DIRECT_NUMBER_ASK_RX = re.compile(
    r"\b(number|phone|mobile|contact details?|text|call)\b", re.I
)
_TENANT_SHARED_NUMBER_RX = re.compile(r"\+?44\s?7|\b07\d", re.I)
_TRAVEL_RX = re.compile(
    r"\b(driv(?:e|ing)|travel(?:ling)?|manchester|far|journey|down from)\b", re.I
)
_LOGISTICS_RX = re.compile(
    r"\b(delay(?:ed|s)?|entrance|directions?|finding|updated?|confirm|"
    r"reschedule|video|viewing|time|today|tomorrow|weekend)\b",
    re.I,
)
_SCREENING_RESPONSE_RX = re.compile(
    r"\b(work|job|employ|salary|income|afford|move|moving|tenant|"
    r"husband|wife|partner|profession)\b",
    re.I,
)
_TOO_EAGER_RX = re.compile(
    r"\b(share your contact details|kindly share|please share your contact|"
    r"need your number|send your number)\b",
    re.I,
)


def _previous_tenant_turn(turns: list[dict[str, str]], index: int) -> dict[str, Any] | None:
    for turn in reversed(turns[:index]):
        if turn["speaker"].lower() == "tenant":
            return turn
    return None


def _classify_tenant_message(text: str) -> dict[str, bool]:
    return {
        "asked_directly_for_number": bool(_DIRECT_NUMBER_ASK_RX.search(text)),
        "mentioned_whatsapp": bool(_WHATSAPP_RX.search(text)),
        "shared_tenant_number": bool(_TENANT_SHARED_NUMBER_RX.search(text)),
        "used_travel_context": bool(_TRAVEL_RX.search(text)),
        "used_logistics_context": bool(_LOGISTICS_RX.search(text)),
        "answered_screening": bool(_SCREENING_RESPONSE_RX.search(text)),
        "too_eager_pattern": bool(_TOO_EAGER_RX.search(text)),
    }


def analyze_corpus(path: str | Path) -> dict[str, Any]:
    """Return redacted pattern data for landlord-number success conversations."""

    conversations = parse_corpus(path)
    examples: list[dict[str, Any]] = []
    feature_counts: Counter[str] = Counter()
    success_conversation_ids: set[int] = set()

    for conversation in conversations:
        turns = conversation.get("turns", [])
        for index, turn in enumerate(turns):
            if turn["speaker"].lower() != "landlord":
                continue
            if not contains_phone_signal(turn["text"]):
                continue

            success_conversation_ids.add(conversation["id"])
            previous_tenant = _previous_tenant_turn(turns, index)
            if not previous_tenant:
                continue

            features = _classify_tenant_message(previous_tenant["text"])
            feature_counts.update(
                feature for feature, present in features.items() if present
            )
            examples.append(
                {
                    "conversation_id": conversation["id"],
                    "source": conversation.get("source", ""),
                    "tenant_before_phone": redact_phones(previous_tenant["text"]),
                    "landlord_phone_turn": redact_phones(turn["text"]),
                    "features": features,
                }
            )

    artifact_text = json.dumps(examples, ensure_ascii=False)
    if contains_phone_literal(artifact_text):
        raise RuntimeError("literal phone survived corpus number-capture analysis")

    return {
        "total_conversations": len(conversations),
        "successful_conversations": len(success_conversation_ids),
        "examples": examples,
        "feature_counts": dict(feature_counts),
        "style_guidance": [
            "answer landlord screening first, then return to viewing logistics",
            "use travel, video viewing, timing, or day-of-viewing coordination as the reason",
            "avoid making the number look like the main goal",
            "avoid repeated formal phrases such as 'kindly share your contact details'",
            "if the landlord resists phone or WhatsApp, continue on OpenRent",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--corpus",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "full-conversations.md",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    report = analyze_corpus(args.corpus)
    payload = json.dumps(report, indent=2, ensure_ascii=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    else:
        print(json.dumps(report, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
