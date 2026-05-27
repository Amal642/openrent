"""a3 landlord-patience probe.

Precommit: hippocampus-1:docs/OPENRENT-PILOT-A3-LANDLORD-PATIENCE-PRECOMMIT.md

Goal: confirm (or falsify) the a2 RC diagnosis that the simulated
landlord effectively never offers a specific viewing time within
max_turns=3 on the failed3 multi-turn fixture.

Tests the structural claim by running each scenario N times with no
memory and counting:

  - actor turns that flip signals.viewing_time_offered True
  - trials that reach signals.viewing_confirmed via the safe path
    (i.e., without ever flipping phone_requested_too_early True)

Falsifier (verbatim from the precommit, GREEN/YELLOW/RED bands):

  GREEN  : rate_actor_offers_time_in_window <= 0.10
           AND rate_safe_path_reachable == 0.00
  YELLOW : 0.10 < rate_actor_offers_time_in_window < 0.50
           AND rate_safe_path_reachable <  0.10
  RED    : rate_actor_offers_time_in_window >= 0.50
           OR  rate_safe_path_reachable    >= 0.10

P3 apparatus sanity (asserted before the loop): a synthesized actor
turn containing the word "evening" + a phone pattern flips
viewing_time_offered True on a 2-turn prefix.

Output (under --output-dir):

  <scenario_key>_trials.jsonl  : one row per trial (raw evidence)
  summary.csv                  : one row per scenario (rolled-up rates)
  manifest.json                : fixture id, git sha, command, seed list
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from simulation.conversation_state import (
    analyze_conversation_state,
    _is_ai_phone_request,
)
from simulation.lab import run_simulation_session
from simulation.pilot.fixtures import load_pilot_fixture, PilotScenario


# ---------------------------------------------------------------------- P3

def _p3_sanity_check() -> None:
    """Apparatus precondition: synthesized actor turn containing
    a time word + phone pattern must flip viewing_time_offered True.
    """

    fake_transcript = [
        {"speaker": "agent", "message": "Can I have your phone please?"},
        {
            "speaker": "actor",
            "message": (
                "Sounds good. You can call me on 07123 456 789 this "
                "evening and we can discuss a viewing."
            ),
        },
    ]
    state = analyze_conversation_state(fake_transcript, "viewing_first_v1")
    assert state.signals.viewing_time_offered, (
        "P3 FAILED: signal detector did not flip viewing_time_offered "
        "True on a synthetic 'evening' + phone-pattern actor turn. "
        "The probe's measurement apparatus is broken."
    )


# ---------------------------------------------------------------------- helpers


def _transcript_dicts(transcript: list) -> list[dict]:
    out: list[dict] = []
    for turn in transcript:
        if hasattr(turn, "to_dict"):
            out.append(turn.to_dict())
            continue
        if hasattr(turn, "speaker"):
            out.append(
                {
                    "speaker": turn.speaker,
                    "message": turn.message,
                    "turn_index": getattr(turn, "turn_index", None),
                }
            )
            continue
        out.append(dict(turn))
    return out


def _identify_landlord_branch(message: str) -> str:
    """Classify a landlord message against the reachable branches in
    landlord_actor.py. Branch-5 added in a4 (proactive-offer).
    """

    m = message.lower()
    if m.startswith("hi, thanks for your message"):
        return "branch-1-initial"
    if "sounds good" in m and "call me" in m:
        return "branch-2-phone-shared"
    if "before i share my number" in m:
        return "branch-3-phone-refused"
    if "i still need to know" in m:
        return "branch-4-default-screening"
    if "how about saturday at 2pm" in m:
        return "branch-5-proactive-offer"
    if "i need a proper reply" in m:
        return "branch-0-empty-reply-guard"
    return "branch-unclassified"


def _per_turn_flips(transcript_dicts: list[dict]) -> list[dict]:
    """For each prefix length i, run analyze_conversation_state on
    transcript[:i] and detect first-flip turns for each signal.
    """

    seen: dict[str, bool] = {}
    rows: list[dict] = []
    for i in range(1, len(transcript_dicts) + 1):
        state = analyze_conversation_state(
            transcript_dicts[:i], "viewing_first_v1"
        )
        sig = state.signals
        turn = transcript_dicts[i - 1]
        flipped_now: list[str] = []
        for field, value in asdict(sig).items():
            if value and not seen.get(field):
                flipped_now.append(field)
                seen[field] = True
        rows.append(
            {
                "turn_index_0based": i - 1,
                "speaker": turn.get("speaker"),
                "message": turn.get("message"),
                "agent_asked_phone": (
                    turn.get("speaker") == "agent"
                    and _is_ai_phone_request((turn.get("message") or "").lower())
                ),
                "landlord_branch": (
                    _identify_landlord_branch(turn.get("message") or "")
                    if turn.get("speaker") == "actor"
                    else None
                ),
                "flipped_signals": flipped_now,
                "current_state": state.current_state,
            }
        )
    return rows


def _trial_summary(turn_rows: list[dict], full_transcript: list[dict]) -> dict:
    """Roll up per-trial booleans.

    Per-turn flipped_signals tracks first-flip-True only and is correct
    for monotone-True signals like viewing_time_offered. It is NOT
    correct for end-of-conversation computed signals like
    phone_requested_too_early, which the matrix evaluator computes on
    the final transcript at evaluation time. End-of-transcript fields
    (with the _end suffix) match the matrix's computation and are the
    authoritative metrics for falsifier evaluation.
    """

    actor_offered_time = any(
        row["speaker"] == "actor"
        and "viewing_time_offered" in row["flipped_signals"]
        for row in turn_rows
    )
    first_offer_turn = next(
        (
            row["turn_index_0based"]
            for row in turn_rows
            if row["speaker"] == "actor"
            and "viewing_time_offered" in row["flipped_signals"]
        ),
        None,
    )

    final_state = analyze_conversation_state(full_transcript, "viewing_first_v1")
    sig = final_state.signals
    safe_phone_capture_end = sig.phone_captured and not sig.phone_requested_too_early

    return {
        "actor_offered_time_in_window": actor_offered_time,
        "first_offer_turn_0based": first_offer_turn,
        "phone_captured_end": sig.phone_captured,
        "viewing_confirmed_end": sig.viewing_confirmed,
        "phone_requested_too_early_end": sig.phone_requested_too_early,
        "safe_phone_capture_end": safe_phone_capture_end,
        "final_state": final_state.current_state,
    }


# ---------------------------------------------------------------------- main


def run_one_trial(
    scenario: PilotScenario, seed: int
) -> dict[str, Any]:
    session = run_simulation_session(
        seed=seed,
        max_turns=scenario.max_turns,
        scenario_id=scenario.scenario_id,
        policy_id=scenario.policy_id,
        start_mode=scenario.start_mode,
        initial_message_source=scenario.initial_message_source,
        conversation_design_id=scenario.conversation_design_id,
    )
    transcript = _transcript_dicts(session.get("transcript") or [])
    turn_rows = _per_turn_flips(transcript)
    summary = _trial_summary(turn_rows, transcript)
    return {
        "scenario_key": scenario.scenario_key,
        "seed": seed,
        "max_turns": scenario.max_turns,
        "transcript": transcript,
        "turn_rows": turn_rows,
        "summary": summary,
    }


def _git_sha(repo_root: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=repo_root, text=True
        ).strip()
    except Exception:
        return "unknown"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--fixture",
        required=True,
        type=Path,
        help="Path to pilot fixture JSON (e.g. scenarios.failed3.multi_turn.json).",
    )
    ap.add_argument(
        "--n-trials",
        type=int,
        default=10,
        help="Number of trials per scenario.",
    )
    ap.add_argument(
        "--seed-base",
        type=int,
        default=2000,
        help="First seed; trials use seed_base, seed_base+1, ...",
    )
    ap.add_argument(
        "--output-dir",
        required=True,
        type=Path,
        help="Directory for per-scenario JSONL + summary CSV + manifest.",
    )
    args = ap.parse_args(argv)

    _p3_sanity_check()
    print("P3 sanity check: PASS", flush=True)

    fixture = load_pilot_fixture(args.fixture)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    repo_root = Path(__file__).resolve().parents[2]
    started = time.time()

    summary_rows: list[dict] = []

    for scenario in fixture.scenarios:
        scenario_path = args.output_dir / f"{scenario.scenario_key}_trials.jsonl"
        per_trial: list[dict] = []
        with scenario_path.open("w", encoding="utf-8") as handle:
            for trial_index in range(args.n_trials):
                seed = args.seed_base + trial_index
                t0 = time.time()
                trial = run_one_trial(scenario, seed)
                trial["elapsed_ms"] = int((time.time() - t0) * 1000)
                handle.write(json.dumps(trial) + "\n")
                per_trial.append(trial)
                print(
                    f"  {scenario.scenario_key} seed={seed} "
                    f"offer={trial['summary']['actor_offered_time_in_window']} "
                    f"final={trial['summary']['final_state']}",
                    flush=True,
                )

        n = len(per_trial)
        n_offer = sum(
            1 for t in per_trial if t["summary"]["actor_offered_time_in_window"]
        )
        n_phone_captured = sum(
            1 for t in per_trial if t["summary"]["phone_captured_end"]
        )
        n_safe_phone_capture = sum(
            1 for t in per_trial if t["summary"]["safe_phone_capture_end"]
        )
        n_viewing_confirmed = sum(
            1 for t in per_trial if t["summary"]["viewing_confirmed_end"]
        )
        n_phone_too_early = sum(
            1 for t in per_trial if t["summary"]["phone_requested_too_early_end"]
        )
        offer_turns = [
            t["summary"]["first_offer_turn_0based"]
            for t in per_trial
            if t["summary"]["first_offer_turn_0based"] is not None
        ]
        mean_first_offer = (
            sum(offer_turns) / len(offer_turns) if offer_turns else None
        )

        branch_counts: dict[str, int] = {}
        for trial in per_trial:
            for row in trial["turn_rows"]:
                branch = row.get("landlord_branch")
                if not branch:
                    continue
                branch_counts[branch] = branch_counts.get(branch, 0) + 1

        summary_rows.append(
            {
                "scenario_key": scenario.scenario_key,
                "scenario_id": scenario.scenario_id,
                "max_turns": scenario.max_turns,
                "n_trials": n,
                "rate_actor_offers_time_in_window": n_offer / n if n else 0.0,
                "rate_safe_phone_capture_end": n_safe_phone_capture / n if n else 0.0,
                "rate_phone_captured_end": n_phone_captured / n if n else 0.0,
                "rate_viewing_confirmed_end": n_viewing_confirmed / n if n else 0.0,
                "rate_phone_requested_too_early_end": n_phone_too_early / n if n else 0.0,
                "mean_first_offer_turn_0based": mean_first_offer,
                "landlord_branch_counts_json": json.dumps(branch_counts, sort_keys=True),
            }
        )

    summary_csv = args.output_dir / "summary.csv"
    fieldnames = list(summary_rows[0].keys())
    with summary_csv.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in summary_rows:
            writer.writerow(row)

    pooled_n = sum(r["n_trials"] for r in summary_rows)

    def _pooled(field: str) -> float:
        total = sum(r["n_trials"] * r[field] for r in summary_rows)
        return total / pooled_n if pooled_n else 0.0

    pooled_rate_offer = _pooled("rate_actor_offers_time_in_window")
    pooled_rate_safe_phone_capture = _pooled("rate_safe_phone_capture_end")
    pooled_rate_phone_captured = _pooled("rate_phone_captured_end")
    pooled_rate_viewing_confirmed = _pooled("rate_viewing_confirmed_end")
    pooled_rate_phone_too_early = _pooled("rate_phone_requested_too_early_end")

    # a3 structural-ceiling bands (only meaningful for a3-style probes
    # under the unmodified actor). a4+ smoke runs use the apparatus
    # gate below instead.
    if pooled_rate_offer >= 0.50 or pooled_rate_safe_phone_capture > 0.0:
        a3_verdict = "RED"
    elif pooled_rate_offer <= 0.10 and pooled_rate_safe_phone_capture == 0.0:
        a3_verdict = "GREEN"
    else:
        a3_verdict = "YELLOW"

    # a4 apparatus gate A5: baseline safe_phone_capture_rate must
    # land in [0.20, 0.60] to leave headroom for memory to help.
    if pooled_rate_safe_phone_capture > 0.60:
        a5_verdict = "APPARATUS-RED-TOO-EASY"
    elif pooled_rate_safe_phone_capture < 0.20:
        a5_verdict = "APPARATUS-RED-TOO-HARD"
    else:
        a5_verdict = "APPARATUS-GREEN"

    manifest = {
        "fixture_id": fixture.fixture_id,
        "fixture_path": str(args.fixture),
        "git_sha": _git_sha(repo_root),
        "n_trials_per_scenario": args.n_trials,
        "seed_base": args.seed_base,
        "command": "python -m simulation.pilot.probe_landlord_patience "
        + " ".join(sys.argv[1:]),
        "started_iso": time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime(started)
        ),
        "finished_iso": time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time())
        ),
        "pooled": {
            "n_trials": pooled_n,
            "rate_actor_offers_time_in_window": pooled_rate_offer,
            "rate_safe_phone_capture_end": pooled_rate_safe_phone_capture,
            "rate_phone_captured_end": pooled_rate_phone_captured,
            "rate_viewing_confirmed_end": pooled_rate_viewing_confirmed,
            "rate_phone_requested_too_early_end": pooled_rate_phone_too_early,
            "a3_structural_ceiling_verdict": a3_verdict,
            "a4_apparatus_gate_a5_verdict": a5_verdict,
        },
        "per_scenario": summary_rows,
    }
    (args.output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )

    print(f"\na3 structural-ceiling verdict: {a3_verdict}")
    print(f"a4 apparatus-gate A5 verdict:  {a5_verdict}")
    print(f"  pooled_n = {pooled_n}")
    print(f"  rate_actor_offers_time_in_window = {pooled_rate_offer:.4f}")
    print(f"  rate_safe_phone_capture_end     = {pooled_rate_safe_phone_capture:.4f}")
    print(f"  rate_phone_captured_end         = {pooled_rate_phone_captured:.4f}")
    print(f"  rate_viewing_confirmed_end      = {pooled_rate_viewing_confirmed:.4f}")
    print(f"  rate_phone_requested_too_early_end = {pooled_rate_phone_too_early:.4f}")
    print(f"  artifacts in {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
