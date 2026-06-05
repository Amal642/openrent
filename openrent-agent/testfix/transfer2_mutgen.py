"""
Transfer rung 2: mechanical SQL mutation generator for jaffle_shop_duckdb.

Validity: parent `dbt build` green; mutant `dbt build` has >=1 failure.
<=3 per model. Loop never sees dbt test results.

Usage: python -m testfix.transfer2_mutgen
Output: testfix/transfer2_mutations.json
"""

import json
import random
import re
import subprocess
import sys
from pathlib import Path

REPO = Path("D:/transfer-rung1/jaffle_shop_duckdb")
OUT = Path(__file__).resolve().parent / "transfer2_mutations.json"

OPERATORS = [
    (r"\bsum\(", "count(", "sum_to_count"),
    (r"\bcount\(", "sum(", "count_to_sum"),
    (r"\bmin\(", "max(", "min_to_max"),
    (r"\bmax\(", "min(", "max_to_min"),
    (r"\bleft join\b", "inner join", "leftjoin_to_innerjoin"),
    (r"(?<![<>!:])=(?!=)", "!=", "eq_to_neq"),
    (r"/ 100", "* 100", "div_to_mul"),
    (r"\belse 0\b", "else 1", "else0_to_else1"),
]


def _dbt(cmd: str) -> bool:
    r = subprocess.run(
        ["dbt", cmd, "--no-use-colors"],
        capture_output=True, text=True, cwd=REPO, timeout=300, shell=True,
    )
    return r.returncode == 0


def main() -> None:
    random.seed(7)
    models = sorted(REPO.glob("models/**/*.sql"))
    print("Verifying parent dbt build green...")
    assert _dbt("build"), "parent dbt build must pass"

    candidates = []
    for mp in models:
        src = mp.read_text(encoding="utf-8")
        for i, line in enumerate(src.splitlines(keepends=True)):
            s = line.strip()
            if not s or s.startswith("--") or s.startswith("{#"):
                continue
            for pat, rep, label in OPERATORS:
                if re.search(pat, line, re.IGNORECASE):
                    candidates.append((mp, i, pat, rep, label))
    random.shuffle(candidates)
    print(f"{len(candidates)} candidates across {len(models)} models")

    valid = []
    per_model: dict[str, int] = {}
    for mp, i, pat, rep, label in candidates:
        if len(valid) >= 18:
            break
        rel = str(mp.relative_to(REPO)).replace("\\", "/")
        if per_model.get(rel, 0) >= 3:
            continue
        parent_src = mp.read_text(encoding="utf-8")
        lines = parent_src.splitlines(keepends=True)
        mutated_line = re.sub(pat, rep, lines[i], count=1, flags=re.IGNORECASE)
        if mutated_line == lines[i]:
            continue
        new_lines = lines.copy()
        new_lines[i] = mutated_line
        mp.write_text("".join(new_lines), encoding="utf-8")
        try:
            killed = not _dbt("build")
        finally:
            mp.write_text(parent_src, encoding="utf-8")
        print(f"  {rel} L{i+1} {label}: {'VALID' if killed else 'not-killed'}")
        if killed:
            per_model[rel] = per_model.get(rel, 0) + 1
            valid.append({
                "case_id": f"d{len(valid)+1:03d}",
                "model": rel,
                "lineno": i + 1,
                "operator": label,
                "original_line": lines[i],
                "mutated_line": mutated_line,
            })

    assert _dbt("build"), "parent must be green after mutgen"
    OUT.write_text(json.dumps(valid, indent=2), encoding="utf-8")
    print(f"\n{len(valid)} valid mutations -> {OUT}")
    from collections import Counter
    print(Counter(v["model"] for v in valid))


if __name__ == "__main__":
    main()
