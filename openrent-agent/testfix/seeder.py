"""
testfix.seeder
--------------
Validates seeds and writes a baseline JSONL.

Usage (from openrent-agent/):
    python testfix/seeder.py                  # easy infra suite
    python testfix/seeder.py --suite hard     # hard calibration suite
"""

import argparse
import contextlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

from testfix.extractor import _extract_function_source


def apply_mutation(function_source: str, original_snippet: str, mutated_snippet: str) -> str | None:
    """Replace original_snippet with mutated_snippet once. Returns None if not found."""
    if original_snippet not in function_source:
        return None
    return function_source.replace(original_snippet, mutated_snippet, 1)


def _clear_pyc(py_path: Path) -> None:
    """Delete compiled bytecode for py_path so the next subprocess compiles fresh."""
    import glob
    stem = py_path.stem
    cache_dir = py_path.parent / "__pycache__"
    for pyc in cache_dir.glob(f"{stem}.*.pyc"):
        try:
            pyc.unlink()
        except OSError:
            pass


@contextlib.contextmanager
def _patched_file(path: Path, new_source: str):
    original = path.read_text(encoding="utf-8")
    path.write_text(new_source, encoding="utf-8")
    _clear_pyc(path)
    try:
        yield
    finally:
        path.write_text(original, encoding="utf-8")
        _clear_pyc(path)


def _run_test(test_id: str) -> tuple[bool, str]:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", test_id, "--tb=short", "-q", "--no-header"],
        capture_output=True, text=True, cwd=ROOT,
    )
    return result.returncode == 0, result.stdout + result.stderr


def _replace_function_in_file(file_source: str, function_source: str, mutated_function: str) -> str:
    """Replace the exact function block in the file source."""
    if function_source not in file_source:
        return file_source
    return file_source.replace(function_source, mutated_function, 1)


def validate_seed(seed: dict) -> dict:
    """
    Returns the seed dict augmented with:
      extractor_ok: bool  (test fails on mutated code AND extractor found the target)
      verifier_ok:  bool  (test passes on original code)
      error: str | None
    """
    target_path = ROOT / seed["target_file"]
    func_name = seed["target_function"]
    test_id = seed["test_id"]

    # Extract current function source
    function_source = _extract_function_source(target_path, func_name)
    if not function_source:
        return {**seed, "extractor_ok": False, "verifier_ok": False,
                "error": f"Could not extract {func_name} from {seed['target_file']}"}

    # Apply mutation
    mutated_function = apply_mutation(
        function_source, seed["original_snippet"], seed["mutated_snippet"]
    )
    if mutated_function is None:
        return {**seed, "extractor_ok": False, "verifier_ok": False,
                "error": f"Snippet not found in {func_name}: {seed['original_snippet']!r}"}

    # Build mutated file source
    file_source = target_path.read_text(encoding="utf-8")
    mutated_file = _replace_function_in_file(file_source, function_source, mutated_function)
    if mutated_file == file_source:
        return {**seed, "extractor_ok": False, "verifier_ok": False,
                "error": "Function source not found in file for replacement"}

    # Step 1: test must FAIL on mutated code
    with _patched_file(target_path, mutated_file):
        mutation_fails, mutation_output = _run_test(test_id)

    if mutation_fails:
        return {**seed, "extractor_ok": False, "verifier_ok": False,
                "error": "Mutation did not cause test failure — seed is invalid"}

    # Step 2: test must PASS on original code (sanity)
    original_passes, _ = _run_test(test_id)
    if not original_passes:
        return {**seed, "extractor_ok": False, "verifier_ok": False,
                "error": "Test fails on original code — pre-existing failure, not a valid seed"}

    return {**seed, "extractor_ok": True, "verifier_ok": True, "error": None}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", choices=["easy", "hard", "cross"], default="easy")
    args = parser.parse_args()

    if args.suite == "hard":
        from testfix.seeds_hard import SEEDS_HARD as seeds
        out_filename = "baseline_hard_calibration.jsonl"
        suite_label = "hard calibration"
        include_smoke = False
    elif args.suite == "cross":
        from testfix.seeds_cross import SEEDS_CROSS as seeds
        out_filename = "baseline_cross_function.jsonl"
        suite_label = "cross-function calibration"
        include_smoke = False
    else:
        from testfix.seeds import SEEDS as seeds
        out_filename = "baseline_cases.jsonl"
        suite_label = "easy infra validation"
        include_smoke = True

    print(f"Validating {len(seeds)} seeds ({suite_label})...\n")

    results = []
    passed = 0

    for seed in seeds:
        case_id = seed["case_id"]
        print(f"  {case_id} ({seed['failure_mode']})...", end=" ", flush=True)
        result = validate_seed(seed)

        if result["extractor_ok"] and result["verifier_ok"]:
            print("OK")
            passed += 1
        else:
            print(f"FAIL -- {result.get('error', 'unknown')}")

        record = {k: v for k, v in result.items()
                  if k not in ("original_snippet", "mutated_snippet", "expected_fix_summary")}
        results.append(record)

    out_path = ROOT / "testfix" / out_filename
    with out_path.open("w", encoding="utf-8") as f:
        if include_smoke:
            smoke = {
                "case_id": "smoke_001",
                "source_type": "natural_regression",
                "test_id": "tests/test_stages.py::test_detect_stage_implicit_reschedule_smoke",
                "target_file": "app/ai/stages.py",
                "target_function": "detect_stage",
                "failure_mode": "regex_pattern_missing_case",
                "expected_fix_summary": "Add implicit reschedule pattern (need to change) to the detect_stage guard.",
                "extractor_ok": True,
                "verifier_ok": True,
                "error": None,
                "exclude_from_headline": True,
            }
            f.write(json.dumps(smoke) + "\n")
        for r in results:
            f.write(json.dumps(r) + "\n")

    total_with_smoke = len(results) + (1 if include_smoke else 0)
    print(f"\n{passed}/{len(seeds)} seeds valid")
    print(f"Baseline written to {out_path} ({total_with_smoke} total cases)")


if __name__ == "__main__":
    main()
