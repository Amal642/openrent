"""
OPEN-55b secondary analysis: test-function-level filtering.

Operational rationale: in a commit-diff workflow the parent commit is
available, so generated test FUNCTIONS that fail on the parent (original)
are auto-discarded. The surviving functions form the regression suite.
A case is killed-after-filter when at least one surviving function fails
on the mutant.

This is the operationally correct unit (test function, not whole file).
Reported as a SECONDARY metric alongside the precommitted file-level one.

Usage: python -m testfix.open55b_filter_analysis
"""

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

from testfix.open55b_testgen import (
    _ENTRY_MAP, _apply_seed_mutation, _clear_pyc, _load_seeds,
)


def _run_pytest_verbose(path: Path) -> dict[str, str]:
    """Run pytest -v on a file; return {test_function_name: 'passed'|'failed'}."""
    result = subprocess.run(
        [sys.executable, "-m", "pytest", str(path), "-v", "--tb=no", "--no-header"],
        capture_output=True, text=True, cwd=ROOT,
    )
    output = result.stdout + result.stderr
    outcomes = {}
    for line in output.splitlines():
        m = re.match(r".*::(\w+)(?:\[.*\])?\s+(PASSED|FAILED|ERROR)", line)
        if m:
            name, status = m.group(1), m.group(2)
            # Parametrized tests: a function fails if ANY param fails
            if outcomes.get(name) == "failed":
                continue
            outcomes[name] = "passed" if status == "PASSED" else "failed"
    return outcomes


def _split_test_functions(code: str) -> tuple[str, dict[str, str]]:
    """Return (header, {test_name: source incl. decorators}).

    AST-based (OPEN-59 apparatus fix). The old line-regex version had a 5-line
    decorator lookahead that silently dropped multi-line @parametrize decorators
    from reassembled blocks (-> 'fixture not found' collection errors), and let
    non-test helper defs land inside a preceding test's block (helpers vanished
    when that test was filtered out). Header = EVERYTHING that is not a test
    function (imports, constants, helper defs, fixtures); each test function is
    extracted with its full decorator list.
    """
    import ast as _ast
    try:
        tree = _ast.parse(code)
    except SyntaxError:
        return code, {}
    lines = code.splitlines(keepends=True)
    funcs: dict[str, str] = {}
    test_spans: list[tuple[int, int]] = []
    for node in tree.body:
        if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)) and node.name.startswith("test_"):
            start = min([node.lineno] + [d.lineno for d in node.decorator_list]) - 1
            end = node.end_lineno
            funcs[node.name] = "".join(lines[start:end]) + "\n"
            test_spans.append((start, end))
    if not funcs:
        return code, {}
    header_lines = []
    for i, line in enumerate(lines):
        if not any(s <= i < e for s, e in test_spans):
            header_lines.append(line)
    return "".join(header_lines), funcs


def main() -> None:
    data = json.loads((ROOT / "testfix/open55b_results.json").read_text(encoding="utf-8"))
    seeds = {s["case_id"]: s for s in _load_seeds()}

    rows = []
    for r in data["results"]:
        case_id = r["case_id"]
        code = r["generated_code"]
        if not code:
            rows.append((case_id, r["outcome"], "no_code", 0, 0))
            continue

        seed = seeds[case_id]
        target_path = ROOT / seed["target_file"]
        mutated_src = _apply_seed_mutation(seed)

        # 1. Run full file on ORIGINAL, get per-function outcomes
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", prefix=f"o55bf_{case_id}_orig_",
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
        n_total = len(funcs)
        n_surv = len(survivors)

        if not survivors:
            rows.append((case_id, r["outcome"], "no_survivors", n_total, 0))
            continue

        filtered_code = header + "".join(funcs[n] for n in survivors)

        # 2. Run filtered file on MUTANT
        original_src = target_path.read_text(encoding="utf-8")
        target_path.write_text(mutated_src, encoding="utf-8")
        _clear_pyc(target_path)
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".py", prefix=f"o55bf_{case_id}_mut_",
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

        verdict = "killed_after_filter" if mutant_failed else "survived_filter_no_kill"
        rows.append((case_id, r["outcome"], verdict, n_total, n_surv))

    print(f"{'case_id':<12} {'file-level':<16} {'filtered verdict':<26} {'tests':<6} {'survivors'}")
    print("-" * 72)
    kills = 0
    for case_id, file_level, verdict, n_total, n_surv in rows:
        if verdict == "killed_after_filter":
            kills += 1
        print(f"{case_id:<12} {file_level:<16} {verdict:<26} {n_total:<6} {n_surv}")
    n = len(rows)
    print("-" * 72)
    print(f"Killed after test-function filter: {kills}/{n} = {kills/n:.1%}")


if __name__ == "__main__":
    main()
