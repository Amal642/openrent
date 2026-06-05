"""
OPEN-60 Leg 1: artifact-clean the episode stream, refit ELIG priors.

Cleaning rule (label-free, per OPEN-60-precommit.md): a success episode is an
ARTIFACT iff repaired_fn is neither the detected entry function nor one of its
transitive callees (static call graph over app/). Flagged successes are
re-labeled failures for credit purposes.

Output: testfix/open60_priors_ELIG_clean.json  (+ a cleaning report)

Usage: python -m testfix.open60_clean
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

from testfix.open57_loop import _build_call_graph
from testfix.open59_credit import (
    EPISODE_FILES, _credit_episode, _z_normalize, LAMBDA,
)

HELD_OUT = {"cross_002", "cross_008", "cross_014", "cross_016", "cross_017", "cross_018"}


def _transitive_callees(fn: str, calls: dict[str, set[str]]) -> set[str]:
    seen, frontier = set(), [fn]
    while frontier:
        cur = frontier.pop()
        for callee in calls.get(cur, ()):
            if callee not in seen:
                seen.add(callee)
                frontier.append(callee)
    return seen


def main() -> None:
    # callers_of maps callee -> callers; rebuild forward map for callees
    callers_of, def_file = _build_call_graph()
    calls: dict[str, set[str]] = {}
    for callee, callers in callers_of.items():
        for caller in callers:
            calls.setdefault(caller, set()).add(callee)

    episodes, flagged = [], []
    for name in EPISODE_FILES:
        path = ROOT / "testfix" / name
        if not path.exists():
            continue
        for r in json.loads(path.read_text(encoding="utf-8"))["results"]:
            if r["case_id"] in HELD_OUT:
                continue
            ep = dict(r)
            if ep.get("loop_success") and ep.get("repaired_fn") and ep.get("detected_by"):
                entry = ep["detected_by"].split("::")[0]
                legit = (ep["repaired_fn"] == entry
                         or ep["repaired_fn"] in _transitive_callees(entry, calls))
                if not legit:
                    flagged.append((name, ep["case_id"], entry, ep["repaired_fn"]))
                    ep["loop_success"] = False  # re-label for credit purposes
                    # attempts: the spuriously-verified attempt becomes False
                    ep["attempts"] = [[fn, False] for fn, _ in (ep.get("attempts") or [])]
            episodes.append(ep)

    print(f"Episodes: {len(episodes)}  artifacts flagged: {len(flagged)}")
    for src, cid, entry, fn in flagged:
        print(f"  {src} {cid}: repaired '{fn}' unreachable from entry '{entry}'")

    totals: dict[str, float] = {}
    for ep in episodes:
        for fn, v in _credit_episode(ep, LAMBDA, freq_mode=False).items():
            totals[fn] = totals.get(fn, 0.0) + v
    priors = _z_normalize(totals)
    out = ROOT / "testfix/open60_priors_ELIG_clean.json"
    out.write_text(json.dumps(priors, indent=2), encoding="utf-8")
    top = sorted(priors.items(), key=lambda kv: -kv[1])[:5]
    bot = sorted(priors.items(), key=lambda kv: kv[1])[:3]
    print(f"\ncleaned-ELIG -> {out.name}")
    print(f"  top: {[(f, round(v,2)) for f, v in top]}")
    print(f"  bottom: {[(f, round(v,2)) for f, v in bot]}")

    report = ROOT / "testfix/open60_cleaning_report.json"
    report.write_text(json.dumps(
        {"n_episodes": len(episodes), "flagged": flagged}, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
