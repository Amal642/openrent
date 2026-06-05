"""
Transfer rung 2: oracle-density measurement.

For every mutation candidate mutgen tested (same seed -> same order), measure:
  native_kill : does the repo's own dbt test suite fail? (native oracle)
  diff_catch  : do model OUTPUT tables diverge from parent? (mined oracle)

By construction a mutation is a semantic change iff outputs diverge on the
seed data, so diff_catch is also the ground-truth sensitivity reference.

Usage: python -m testfix.transfer2_density
"""

import json
import random
import re
import subprocess
from pathlib import Path

REPO = Path("D:/transfer-rung1/jaffle_shop_duckdb")
OUT = Path(__file__).resolve().parent / "transfer2_density.json"

from testfix.transfer2_mutgen import OPERATORS
from testfix.transfer2_loop import _dbt, _snapshot_tables, _divergent_models


def main() -> None:
    random.seed(7)
    models = sorted(REPO.glob("models/**/*.sql"))
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

    ok, _ = _dbt("run")
    assert ok
    parent_snap = _snapshot_tables()

    rows = []
    for mp, i, pat, rep, label in candidates[:40]:
        rel = str(mp.relative_to(REPO)).replace("\\", "/")
        parent_src = mp.read_text(encoding="utf-8")
        lines = parent_src.splitlines(keepends=True)
        mutated = re.sub(pat, rep, lines[i], count=1, flags=re.IGNORECASE)
        if mutated == lines[i]:
            continue
        new = lines.copy()
        new[i] = mutated
        mp.write_text("".join(new), encoding="utf-8")
        try:
            run_ok, _ = _dbt("run")
            diff_catch = None
            if run_ok:
                snap = _snapshot_tables()
                diff_catch = bool(snap) and bool(_divergent_models(parent_snap, snap))
            else:
                diff_catch = True  # build error is trivially caught
            native_kill = not _dbt("build")[0]
            # (tuple-returning _dbt from transfer2_loop used throughout)
        finally:
            mp.write_text(parent_src, encoding="utf-8")
        rows.append({"model": rel, "lineno": i + 1, "operator": label,
                     "native_kill": native_kill, "diff_catch": diff_catch})
        print(f"  {rel} L{i+1} {label}: native={native_kill} diff={diff_catch}")

    _dbt("run")  # restore parent DB state
    n = len(rows)
    nk = sum(r["native_kill"] for r in rows)
    dc = sum(r["diff_catch"] for r in rows)
    both = sum(r["native_kill"] and r["diff_catch"] for r in rows)
    only_diff = sum(r["diff_catch"] and not r["native_kill"] for r in rows)
    only_native = sum(r["native_kill"] and not r["diff_catch"] for r in rows)
    silent = sum(not r["native_kill"] and not r["diff_catch"] for r in rows)
    print("\n" + "=" * 60)
    print(f"ORACLE DENSITY  n={n} mutation candidates")
    print(f"  native (dbt tests) kills : {nk}/{n}")
    print(f"  mined (output-diff) catches: {dc}/{n}")
    print(f"  both: {both}  only-mined: {only_diff}  only-native: {only_native}  neither: {silent}")
    OUT.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(f"Results: {OUT}")


if __name__ == "__main__":
    main()
