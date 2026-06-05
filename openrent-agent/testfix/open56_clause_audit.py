"""
OPEN-56 mechanism level (L1): clause-coverage audit.

Each of the 20 mutations violates exactly one spec clause. This audit checks,
for each arm's extracted spec of the relevant entry function, whether that
clause is STATED (keyword probes + manual review of hits).

Scoring: a clause counts as "stated" when all probe groups match the spec text
(case-insensitive; a group matches when ANY of its alternatives appears).
Keyword probing is crude — the printed per-clause matrix is meant to be eyeballed
before being quoted.

Precommit gate: E-all must state >= 12/20 clauses for Mechanism GREEN.

Usage: python -m testfix.open56_clause_audit
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# (case_id, entry_func, clause description, probe groups)
# A probe group is a list of alternatives; clause stated = every group matches.
CLAUSES = [
    ("cross_001", "detect_stage",
     "only the most recent 8 messages count",
     [["recent", "last"], ["8", "eight"]]),
    ("cross_002", "detect_landlord_attitude",
     "'inbound' sender counts as landlord",
     [["inbound"]]),
    ("cross_003", "latest_landlord_asked_for_phone",
     "'phone' is a trigger keyword",
     [["phone"]]),
    ("cross_004", "viewing_requested",
     "text read from the 'message' key",
     [["message", "'message'", '"message"']]),
    ("cross_005", "detect_stage",
     "a single booked pattern suffices (any, not all)",
     [["single", "any", "one of", "at least one"]]),
    ("cross_006", "outbound_count",
     "sender read from the 'sender' key",
     [["sender"]]),
    ("cross_007", "phone_shared_state",
     "'tenant' sender included in scan",
     [["tenant"]]),
    ("cross_008", "detect_stage",
     "text read from the 'message' key",
     [["message", "'message'", '"message"']]),
    ("cross_009", "detect_stage",
     "booking requires presence of a time",
     [["time"]]),
    ("cross_010", "extract_viewing_datetime",
     "'tomorrow' resolves to next day",
     [["tomorrow"]]),
    ("cross_011", "extract_viewing_datetime",
     "plain time without a date must be accepted",
     [["no date", "without a date", "no numeric date", "only a time", "time alone",
       "no calendar date", "date is absent", "plain time"]]),
    ("cross_012", "get_conversation_style",
     "alias friendly_couple -> warm_casual (alias table)",
     [["alias", "friendly_couple"]]),
    ("cross_013", "should_share_phone_now",
     "conversation_style normalised through aliases before the immediate check",
     [["alias", "normalis", "normaliz", "resolve"]]),
    ("cross_014", "detect_landlord_attitude",
     "text read from the 'message' key",
     [["message", "'message'", '"message"']]),
    ("cross_015", "detect_landlord_attitude",
     "sender matching is case-insensitive",
     [["case-insensitive", "case insensitive", "lowercase", "lower case", "lower()"]]),
    ("cross_016", "phone_shared_state",
     "digits compared ignoring non-digit characters",
     [["digit"], ["ignor", "strip", "non-digit", "remove"]]),
    ("cross_017", "outbound_count",
     "sender matching is case-insensitive",
     [["case-insensitive", "case insensitive", "lowercase", "lower case", "lower()"]]),
    ("cross_018", "extract_viewing_datetime",
     "times not excluded when no date spans present",
     [["no date", "without a date", "no numeric date", "only a time", "time alone",
       "no calendar date", "date is absent", "plain time"]]),
    ("cross_019", "detect_stage",
     "keywords match mid-sentence (search, not match-at-start)",
     [["mid-sentence", "anywhere", "substring", "within the", "search"]]),
    ("cross_020", "landlord_messages",
     "'direction' key is a fallback for 'sender'",
     [["direction"]]),
]

ARMS = ["E1", "E2", "E3", "E4", "E-code", "E-all"]


def _clause_stated(spec: str, probe_groups: list[list[str]]) -> bool:
    # Exclude lines that mark the aspect as UNSPECIFIED — a probe word inside
    # an "UNSPECIFIED: ..." line is a mention, not an assertion.
    text = "\n".join(
        line for line in spec.splitlines() if "unspecified" not in line.lower()
    ).lower()
    return all(any(alt.lower() in text for alt in group) for group in probe_groups)


def main() -> None:
    specs = json.loads((ROOT / "testfix/open56_specs.json").read_text(encoding="utf-8"))

    print(f"{'case_id':<12} {'clause':<58} " + " ".join(f"{a:>7}" for a in ARMS))
    print("-" * (12 + 59 + 8 * len(ARMS)))
    totals = {a: 0 for a in ARMS}
    for case_id, fn, desc, probes in CLAUSES:
        row = []
        for arm in ARMS:
            spec = specs[arm].get(fn, "")
            hit = _clause_stated(spec, probes)
            totals[arm] += int(hit)
            row.append("  YES  " if hit else "   .   ")
        print(f"{case_id:<12} {desc[:57]:<58} " + " ".join(row))
    print("-" * (12 + 59 + 8 * len(ARMS)))
    print(f"{'TOTAL':<71} " + " ".join(f"{totals[a]:>4}/20" for a in ARMS))
    print()
    gate = totals["E-all"]
    print(f"Mechanism gate (E-all >= 12/20): {'GREEN' if gate >= 12 else 'RED'}  ({gate}/20)")


if __name__ == "__main__":
    main()
