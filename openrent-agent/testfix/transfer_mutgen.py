"""
Transfer rung 1: mechanical mutation generator for a foreign repo.

AST-guided, line-based mutations (no hand-authoring). Validity filter:
repo suite passes on parent, fails on mutant. <=2 valid mutations per
function, target n>=20.

Usage: python -m testfix.transfer_mutgen
Output: testfix/transfer_mutations.json
"""

import ast
import json
import random
import re
import subprocess
import sys
from pathlib import Path

REPO = Path("D:/transfer-rung1/python-tabulate")
TARGET = REPO / "tabulate/__init__.py"
OUT = Path(__file__).resolve().parent / "transfer_mutations.json"

# (pattern, replacement, label) — applied to a single line, first occurrence
OPERATORS = [
    (r"==", "!=", "eq_to_neq"),
    (r"!=", "==", "neq_to_eq"),
    (r"(?<![<>=!])<(?!=)", "<=", "lt_to_le"),
    (r"<=", "<", "le_to_lt"),
    (r"(?<![<>=!])>(?!=)", ">=", "gt_to_ge"),
    (r">=", ">", "ge_to_gt"),
    (r"\band\b", "or", "and_to_or"),
    (r"\bor\b", "and", "or_to_and"),
    (r"\.startswith\(", ".endswith(", "startswith_to_endswith"),
    (r"\.endswith\(", ".startswith(", "endswith_to_startswith"),
    (r"\.lstrip\(", ".rstrip(", "lstrip_to_rstrip"),
    (r"\.rstrip\(", ".lstrip(", "rstrip_to_lstrip"),
    (r"\.lower\(\)", ".upper()", "lower_to_upper"),
    (r"\bmin\(", "max(", "min_to_max"),
    (r"\bmax\(", "min(", "max_to_min"),
    (r"\bis None\b", "is not None", "isnone_flip"),
    (r"\bis not None\b", "is None", "isnotnone_flip"),
]


def _run_suite() -> bool:
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "test/", "-q", "--no-header", "-x", "--tb=no"],
        capture_output=True, text=True, cwd=REPO, timeout=300,
    )
    return r.returncode == 0


def _function_spans(src: str) -> dict[str, tuple[int, int]]:
    tree = ast.parse(src)
    return {
        n.name: (n.lineno, n.end_lineno)
        for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def main() -> None:
    random.seed(42)
    parent_src = TARGET.read_text(encoding="utf-8")
    lines = parent_src.splitlines(keepends=True)
    spans = _function_spans(parent_src)

    print("Verifying parent suite passes...")
    assert _run_suite(), "parent suite must pass"

    # Build candidate (line_idx, fn, op) list — body lines only, skip
    # docstrings/comments/defs
    candidates = []
    for fn, (start, end) in spans.items():
        for i in range(start, end):  # 1-indexed lineno -> body lines after def
            line = lines[i] if i < len(lines) else ""
            s = line.strip()
            if not s or s.startswith("#") or s.startswith('"') or s.startswith("'"):
                continue
            if s.startswith("def ") or s.startswith("class "):
                continue
            for pat, rep, label in OPERATORS:
                if re.search(pat, line.split("#")[0]):
                    candidates.append((i, fn, pat, rep, label))
    random.shuffle(candidates)
    print(f"{len(candidates)} candidate mutations across {len(spans)} functions")

    valid = []
    per_fn: dict[str, int] = {}
    tried = 0
    for i, fn, pat, rep, label in candidates:
        if len(valid) >= 24:
            break
        if per_fn.get(fn, 0) >= 2:
            continue
        original_line = lines[i]
        mutated_line = re.sub(pat, rep, original_line.split("#")[0], count=1)
        if "#" in original_line:
            mutated_line += "#" + original_line.split("#", 1)[1]
        if mutated_line == original_line:
            continue
        # syntax check
        new_lines = lines.copy()
        new_lines[i] = mutated_line if mutated_line.endswith("\n") else mutated_line + "\n"
        new_src = "".join(new_lines)
        try:
            ast.parse(new_src)
        except SyntaxError:
            continue

        tried += 1
        TARGET.write_text(new_src, encoding="utf-8")
        try:
            killed = not _run_suite()
        finally:
            TARGET.write_text(parent_src, encoding="utf-8")
        status = "VALID" if killed else "not-killed"
        print(f"  [{tried}] {fn} L{i+1} {label}: {status}  ({len(valid)+ (1 if killed else 0)} valid)")
        if killed:
            per_fn[fn] = per_fn.get(fn, 0) + 1
            valid.append({
                "case_id": f"t{len(valid)+1:03d}",
                "function": fn,
                "lineno": i + 1,
                "operator": label,
                "original_line": original_line,
                "mutated_line": new_lines[i],
            })

    OUT.write_text(json.dumps(valid, indent=2), encoding="utf-8")
    fns = sorted({v['function'] for v in valid})
    print(f"\n{len(valid)} valid mutations across {len(fns)} functions -> {OUT}")
    print("functions:", fns)


if __name__ == "__main__":
    main()
