"""
OPEN-56 step 3: run spec-conditioned test generation per arm.

Reuses the OPEN-55b machinery (same generation prompt shape, same validator,
same model) with the spec body swapped for the extracted spec. S0 is the
signature-only ablation floor (no spec body at all).

Output per arm: testfix/open56_results_<arm>.json  (same schema as open55b_results.json,
so open55b_filter_analysis logic can be reused).

Usage:
    python -m testfix.open56_run --arm S0
    python -m testfix.open56_run --arm E-all
    python -m testfix.open56_run --all
"""

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

from testfix.open55b_testgen import (
    _ENTRY_MAP, _STATUS_CONSTANTS, SIGNATURES,
    _apply_seed_mutation, _call_model, _calls_private_helper, _classify,
    _clear_pyc, _count_test_functions, _has_real_assertion, _load_seeds,
    _run_generated_test,
)

ARMS = ["S0", "E1", "E2", "E3", "E4", "E-code", "E-all"]


def _build_prompt_s0(entry_func: str, entry_file: str) -> str:
    module_dotpath = entry_file.replace("/", ".").replace("\\", ".").removesuffix(".py")
    sig = SIGNATURES[entry_func]
    return f"""You are a test engineer. Write pytest tests for the function below. You have ONLY its signature — no implementation and no further specification.

=== Function ===
{sig}

Import as: from {module_dotpath} import {entry_func}

=== Status constants (app/db/status.py) — import what you need ===
{_STATUS_CONSTANTS}

=== Your task ===
Write 3–6 pytest test functions that:
1. Verify the behaviour you infer from the function name and signature.
2. Use realistic inputs and assert SPECIFIC expected return values.
3. Do NOT directly call private helpers (names starting with `_`). Test only through `{entry_func}`.
4. Every test must assert a concrete expected value (== comparisons or `is True`/`is False`).

Return ONLY valid Python code (imports + test functions). No explanation, no markdown fences.
"""


def _build_prompt_extracted(entry_func: str, entry_file: str, spec: str) -> str:
    module_dotpath = entry_file.replace("/", ".").replace("\\", ".").removesuffix(".py")
    sig = SIGNATURES[entry_func]
    return f"""You are a test engineer. Write pytest tests for the function below from its SPECIFICATION ONLY — you do not have access to the implementation.

=== Function ===
{sig}

Import as: from {module_dotpath} import {entry_func}

=== Specification ===
{spec}

=== Status constants (app/db/status.py) — import what you need ===
{_STATUS_CONSTANTS}

=== Your task ===
Write 3–6 pytest test functions that:
1. Verify the SPECIFIED behaviour precisely — every clause of the contract that can be tested cheaply should have a test.
2. Use realistic inputs and assert SPECIFIC expected return values.
3. Pay particular attention to edge cases the specification calls out explicitly (fallback keys, case-insensitivity, mid-sentence keywords, boundary counts, alias resolution, etc.).
4. Where the specification marks an aspect UNSPECIFIED, do NOT write a test for that aspect.
5. Do NOT directly call private helpers (names starting with `_`). Test only through `{entry_func}`.
6. Every test must assert a concrete expected value (== comparisons or `is True`/`is False`).

Return ONLY valid Python code (imports + test functions). No explanation, no markdown fences.
"""


def run_arm(arm: str, model: str, specs: dict | None) -> list[dict]:
    seeds = _load_seeds()
    results = []

    for seed in seeds:
        case_id = seed["case_id"]
        entry_info = _ENTRY_MAP[case_id]
        entry_func = entry_info["entry_func"]
        entry_file = entry_info["entry_file"]
        target_path = ROOT / seed["target_file"]

        mutated_src = _apply_seed_mutation(seed)
        if mutated_src is None:
            print(f"[{arm}/{case_id}] SKIP — mutation snippet not found")
            continue

        if arm == "S0":
            prompt = _build_prompt_s0(entry_func, entry_file)
        else:
            spec = specs[arm][entry_func]
            prompt = _build_prompt_extracted(entry_func, entry_file, spec)

        generated, latency_ms = _call_model(prompt, model)
        if not generated:
            results.append({
                "case_id": case_id, "entry_func": entry_func,
                "target_function": seed["target_function"],
                "outcome": "no_generation", "generated_code": None,
                "calls_private_helper": False, "has_real_assertion": False,
                "n_test_functions": 0, "latency_ms": round(latency_ms),
            })
            continue

        on_original, _ = _run_generated_test(generated, f"56{arm.replace('-','')}_{case_id}_o")

        original_src = target_path.read_text(encoding="utf-8")
        target_path.write_text(mutated_src, encoding="utf-8")
        _clear_pyc(target_path)
        try:
            on_mutant, _ = _run_generated_test(generated, f"56{arm.replace('-','')}_{case_id}_m")
        finally:
            target_path.write_text(original_src, encoding="utf-8")
            _clear_pyc(target_path)

        outcome = _classify(on_mutant, on_original)
        print(f"  [{arm}/{case_id}] on_original={on_original}  on_mutant={on_mutant}  outcome={outcome}")

        results.append({
            "case_id": case_id, "entry_func": entry_func,
            "target_function": seed["target_function"],
            "outcome": outcome,
            "calls_private_helper": _calls_private_helper(generated),
            "has_real_assertion": _has_real_assertion(generated),
            "n_test_functions": _count_test_functions(generated),
            "latency_ms": round(latency_ms),
            "generated_code": generated,
        })

    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--arm", choices=ARMS)
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--model", default="gpt-4.1-mini")
    args = parser.parse_args()

    arms = ARMS if args.all else [args.arm]
    specs = None
    if any(a != "S0" for a in arms):
        specs = json.loads((ROOT / "testfix/open56_specs.json").read_text(encoding="utf-8"))

    for arm in arms:
        print(f"\n=== ARM {arm} ===")
        results = run_arm(arm, args.model, specs)
        from collections import Counter
        outcomes = Counter(r["outcome"] for r in results)
        n = len(results)
        kr = outcomes["killed"] / n if n else 0
        print(f"  {arm}: killed={outcomes['killed']}/{n} = {kr:.1%}  "
              f"fp={outcomes['false_positive']}  bp={outcomes['both_pass']}  "
              f"inv={outcomes['inverted']}  err={outcomes['syntax_error']}")
        out = ROOT / f"testfix/open56_results_{arm}.json"
        out.write_text(
            json.dumps({"model": args.model, "arm": arm, "results": results}, indent=2),
            encoding="utf-8",
        )
        print(f"  written: {out}")


if __name__ == "__main__":
    main()
