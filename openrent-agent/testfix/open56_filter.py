"""
OPEN-56: commit-diff filter analysis per arm (test-function granularity).

Same protocol as open55b_filter_analysis: drop generated test FUNCTIONS that
fail on the original (parent commit), run survivors on the mutant; a case is
killed_after_filter when any survivor fails.

Usage: python -m testfix.open56_filter            # all arms found on disk
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

from testfix.open55b_testgen import _apply_seed_mutation, _clear_pyc, _load_seeds
from testfix.open55b_filter_analysis import _run_pytest_verbose, _split_test_functions

ARMS = ["S0", "E1", "E2", "E3", "E4", "E-code", "E-all"]


def analyse_arm(arm: str) -> tuple[int, int, list]:
    path = ROOT / f"testfix/open56_results_{arm}.json"
    if not path.exists():
        return 0, 0, []
    data = json.loads(path.read_text(encoding="utf-8"))
    seeds = {s["case_id"]: s for s in _load_seeds()}

    rows = []
    kills = 0
    for r in data["results"]:
        case_id = r["case_id"]
        code = r.get("generated_code")
        if not code:
            rows.append((case_id, r["outcome"], "no_code", 0, 0))
            continue

        seed = seeds[case_id]
        target_path = ROOT / seed["target_file"]
        mutated_src = _apply_seed_mutation(seed)

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", prefix=f"o56f_{arm.replace('-','')}_{case_id}_o_",
            dir=ROOT / "testfix", delete=False, encoding="utf-8",
        ) as f:
            f.write(code)
            tmp = Path(f.name)
        try:
            orig_outcomes = _run_pytest_verbose(tmp)
        finally:
            tmp.unlink(missing_ok=True)

        header, funcs = _split_test_functions(code)
        survivors = [n for n, src in funcs.items() if orig_outcomes.get(n) == "passed"]

        if not survivors:
            rows.append((case_id, r["outcome"], "no_survivors", len(funcs), 0))
            continue

        filtered_code = header + "".join(funcs[n] for n in survivors)
        original_src = target_path.read_text(encoding="utf-8")
        target_path.write_text(mutated_src, encoding="utf-8")
        _clear_pyc(target_path)
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".py", prefix=f"o56f_{arm.replace('-','')}_{case_id}_m_",
                dir=ROOT / "testfix", delete=False, encoding="utf-8",
            ) as f:
                f.write(filtered_code)
                tmp = Path(f.name)
            try:
                result = subprocess.run(
                    [sys.executable, "-m", "pytest", str(tmp), "--tb=no", "-q", "--no-header"],
                    capture_output=True, text=True, cwd=ROOT,
                )
                mutant_failed = result.returncode != 0
            finally:
                tmp.unlink(missing_ok=True)
        finally:
            target_path.write_text(original_src, encoding="utf-8")
            _clear_pyc(target_path)

        verdict = "killed_after_filter" if mutant_failed else "survived_no_kill"
        if mutant_failed:
            kills += 1
        rows.append((case_id, r["outcome"], verdict, len(funcs), len(survivors)))

    return kills, len(rows), rows


def main() -> None:
    summary = {}
    for arm in ARMS:
        kills, n, rows = analyse_arm(arm)
        if n == 0:
            continue
        summary[arm] = (kills, n)
        print(f"\n=== {arm}: killed_after_filter {kills}/{n} = {kills/n:.1%}")
        for case_id, file_level, verdict, n_total, n_surv in rows:
            print(f"  {case_id:<12} {file_level:<16} {verdict:<22} tests={n_total} survivors={n_surv}")

    print("\n" + "=" * 50)
    print(f"{'arm':<10} {'filtered kill rate'}")
    print("-" * 50)
    for arm, (kills, n) in summary.items():
        print(f"{arm:<10} {kills}/{n} = {kills/n:.1%}")

    out = ROOT / "testfix/open56_filter_summary.json"
    out.write_text(json.dumps({a: {"killed": k, "n": n} for a, (k, n) in summary.items()}, indent=2), encoding="utf-8")
    print(f"\nSummary: {out}")


if __name__ == "__main__":
    main()
