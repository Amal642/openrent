"""
OPEN-59 Phase B: fit function-level priors from loop episodes, three arms.

Arms (per OPEN-59-precommit.md; lambda=0.5 fixed, NO tuning after eval):
  ELIG  eligibility-decayed +/- credit: stage distance d from verification
        (repair attempt d=0, localizer-ranked candidate d=1, detection d=2),
        credit = outcome * lambda^d  (outcome: +1 verified success episode,
        -1 failed episode; per-attempt verification used at d=0).
  UNIF  same +/- credit, no decay (lambda=1).
  FREQ  success counts only: +1 to functions on the successful path; no
        negatives, no decay.

Episodes: open57_results.json (run #2) + open59_episodes_r*.json.
Output: testfix/open59_priors_{ELIG,UNIF,FREQ}.json  (z-normalized)

Usage:
    python -m testfix.open59_credit                    # train on ALL episodes
    python -m testfix.open59_credit --exclude cross_004,cross_009,...   # leave-out
"""

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

EPISODE_FILES = [
    "open57_results.json",
    "open59_episodes_r3.json",
    "open59_episodes_r4.json",
    "open59_episodes_r5.json",
]

LAMBDA = 0.5


def _load_episodes(exclude: set[str]) -> list[dict]:
    episodes = []
    for name in EPISODE_FILES:
        path = ROOT / "testfix" / name
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        for r in data["results"]:
            if r["case_id"] in exclude:
                continue
            episodes.append(r)
    return episodes


def _credit_episode(ep: dict, lam: float, freq_mode: bool) -> dict[str, float]:
    """Per-episode credit per function."""
    credit: dict[str, float] = {}
    outcome = 1.0 if ep.get("loop_success") else -1.0

    def add(fn: str, value: float) -> None:
        credit[fn] = credit.get(fn, 0.0) + value

    if freq_mode:
        # FREQ: success counts only, successful path only
        if ep.get("loop_success") and ep.get("repaired_fn"):
            add(ep["repaired_fn"], 1.0)
        return credit

    # d=0: repair attempts — per-attempt verified flag is the local outcome
    for fn, verified in ep.get("attempts", []) or []:
        add(fn, (1.0 if verified else -1.0) * lam ** 0)
    # legacy episodes (run #2) lack attempts; fall back to repaired_fn
    if not ep.get("attempts") and ep.get("repaired_fn"):
        add(ep["repaired_fn"], outcome * lam ** 0)

    # d=1: localizer-ranked candidates share the episode outcome
    for fn in ep.get("localizer_top", [])[:2]:
        add(fn, outcome * lam ** 1)

    # d=2: detection entry function shares the episode outcome
    det = ep.get("detected_by")
    if det:
        add(det.split("::")[0], outcome * lam ** 2)

    return credit


def _z_normalize(priors: dict[str, float]) -> dict[str, float]:
    if not priors:
        return priors
    vals = list(priors.values())
    mean = sum(vals) / len(vals)
    var = sum((v - mean) ** 2 for v in vals) / max(1, len(vals) - 1)
    std = var ** 0.5 or 1.0
    return {k: (v - mean) / std for k, v in priors.items()}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exclude", default="", help="comma-separated case_ids to hold out")
    args = parser.parse_args()
    exclude = set(x for x in args.exclude.split(",") if x)

    episodes = _load_episodes(exclude)
    print(f"Training episodes: {len(episodes)}  (excluded cases: {sorted(exclude) or 'none'})")

    arms = {
        "ELIG": dict(lam=LAMBDA, freq_mode=False),
        "UNIF": dict(lam=1.0, freq_mode=False),
        "FREQ": dict(lam=1.0, freq_mode=True),
    }
    for arm, cfg in arms.items():
        totals: dict[str, float] = {}
        for ep in episodes:
            for fn, v in _credit_episode(ep, cfg["lam"], cfg["freq_mode"]).items():
                totals[fn] = totals.get(fn, 0.0) + v
        priors = _z_normalize(totals)
        out = ROOT / f"testfix/open59_priors_{arm}.json"
        out.write_text(json.dumps(priors, indent=2), encoding="utf-8")
        top = sorted(priors.items(), key=lambda kv: -kv[1])[:5]
        bot = sorted(priors.items(), key=lambda kv: kv[1])[:3]
        print(f"\n{arm}: {len(priors)} functions -> {out.name}")
        print(f"  top: {[(f, round(v,2)) for f, v in top]}")
        print(f"  bottom: {[(f, round(v,2)) for f, v in bot]}")


if __name__ == "__main__":
    main()
