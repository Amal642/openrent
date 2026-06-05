"""
Transfer rung 2: the loop on dbt SQL models (jaffle_shop_duckdb).

Stage mapping per TRANSFER-RUNG2-precommit.md:
  trusted ref = parent model OUTPUT tables (sorted row multisets)
  detection   = dbt run on mutant (NO tests), tables diffed vs parent
  localization = first divergent model in DAG topological order
  repair      = locate-then-patch on the localized model's SQL,
                context = mutant SQL + divergence sample
  verification = dbt run + ALL tables match parent
  ground truth (held out) = dbt build green (includes 20 native tests)

Usage: python -m testfix.transfer2_loop
"""

import json
import re
import subprocess
import time
from pathlib import Path

REPO = Path("D:/transfer-rung1/jaffle_shop_duckdb")
DB = REPO / "jaffle_shop.duckdb"
MUTATIONS = Path(__file__).resolve().parent / "transfer2_mutations.json"
OUT = Path(__file__).resolve().parent / "transfer2_results.json"
MODEL = "gpt-4.1-mini"

from testfix.open55b_testgen import _call_model

# DAG topological order (staging -> marts); jaffle_shop is small and static
DAG_ORDER = ["stg_customers", "stg_orders", "stg_payments", "customers", "orders"]
MODEL_FILES = {
    "stg_customers": "models/staging/stg_customers.sql",
    "stg_orders": "models/staging/stg_orders.sql",
    "stg_payments": "models/staging/stg_payments.sql",
    "customers": "models/customers.sql",
    "orders": "models/orders.sql",
}
UPSTREAM = {
    "stg_customers": [],
    "stg_orders": [],
    "stg_payments": [],
    "customers": ["stg_customers", "stg_orders", "stg_payments"],
    "orders": ["stg_orders", "stg_payments"],
}


def _dbt(cmd: str) -> tuple[bool, str]:
    r = subprocess.run(
        ["dbt", cmd, "--no-use-colors"],
        capture_output=True, text=True, cwd=REPO, timeout=300, shell=True,
    )
    return r.returncode == 0, r.stdout + r.stderr


def _snapshot_tables() -> dict[str, list] | None:
    """Read all model tables as sorted row multisets (canonicalization =
    the determinism screen analog for SQL)."""
    import duckdb
    try:
        con = duckdb.connect(str(DB), read_only=True)
        out = {}
        for m in DAG_ORDER:
            rows = con.execute(f'SELECT * FROM "{m}"').fetchall()
            cols = [d[0] for d in con.execute(f'SELECT * FROM "{m}" LIMIT 0').description]
            out[m] = {"cols": cols, "rows": sorted(repr(r) for r in rows)}
        con.close()
        return out
    except Exception:
        return None


def _divergent_models(parent: dict, current: dict) -> list[str]:
    return [m for m in DAG_ORDER
            if parent[m]["rows"] != current[m]["rows"] or parent[m]["cols"] != current[m]["cols"]]


def _divergence_sample(parent: dict, current: dict, m: str, k: int = 5) -> str:
    p, c = parent[m], current[m]
    if p["cols"] != c["cols"]:
        return f"columns differ: expected {p['cols']}, got {c['cols']}"
    p_only = [r for r in p["rows"] if r not in set(c["rows"])][:k]
    c_only = [r for r in c["rows"] if r not in set(p["rows"])][:k]
    lines = [f"columns: {p['cols']}"]
    if p_only:
        lines.append("rows EXPECTED but missing/changed:")
        lines += [f"  {r}" for r in p_only]
    if c_only:
        lines.append("rows PRESENT but wrong:")
        lines += [f"  {r}" for r in c_only]
    if not p_only and not c_only:
        lines.append(f"row counts: expected {len(p['rows'])}, got {len(c['rows'])}")
    return "\n".join(lines)


def _patch_prompt(model_name: str, sql: str, divergence: str) -> str:
    return (
        "You are fixing a bug in a dbt SQL model. The model's output table "
        "diverges from its last known-good (trusted) output on the SAME input "
        "data, so the SQL itself contains a regression.\n\n"
        f"MODEL ({model_name}):\n{sql}\n\n"
        f"OBSERVED DIVERGENCE (expected = trusted output):\n{divergence}\n\n"
        "Produce a MINIMAL patch to the SQL above. Reply in EXACTLY this format:\n"
        "<<<<SEARCH\n"
        "(one or more EXACT consecutive lines copied verbatim from the model)\n"
        "====\n"
        "(the replacement lines)\n"
        ">>>>\n"
        "The SEARCH text must appear exactly once in the model. Change as few "
        "lines as possible. No explanation outside the block."
    )


def _attempt_patch(model_name: str, sql: str, divergence: str) -> str | None:
    raw, _ = _call_model(_patch_prompt(model_name, sql, divergence), MODEL, max_tokens=700)
    if not raw:
        return None
    m = re.search(r"<<<<SEARCH\n(.*?)\n====\n(.*?)\n?>>>>", raw, re.DOTALL)
    if not m:
        return None
    search, replace = m.group(1), m.group(2)
    if sql.count(search) != 1:
        return None
    return sql.replace(search, replace, 1)


def main() -> None:
    mutations = json.loads(MUTATIONS.read_text(encoding="utf-8"))
    parents = {rel: (REPO / rel).read_text(encoding="utf-8")
               for rel in {m["model"] for m in mutations}}

    print("Building parent snapshots (dbt run on parent)...")
    ok, _ = _dbt("run")
    assert ok, "parent dbt run must pass"
    parent_snap = _snapshot_tables()
    assert parent_snap, "parent snapshot failed"

    results = []
    for mut in mutations:
        case_id = mut["case_id"]
        rel = mut["model"]
        path = REPO / rel
        parent_src = parents[rel]
        lines = parent_src.splitlines(keepends=True)
        idx = mut["lineno"] - 1
        assert lines[idx] == mut["original_line"], f"{case_id}: line drift"
        lines[idx] = mut["mutated_line"]

        record = {"case_id": case_id, "true_model": rel, "operator": mut["operator"],
                  "stage": None, "loop_success": False, "ground_truth": False,
                  "localized": None, "attempts": [], "repaired_model": None}

        path.write_text("".join(lines), encoding="utf-8")
        try:
            ok, _ = _dbt("run")
            if not ok:
                # mutant doesn't even build -> detection trivially fires;
                # localization from dbt's own error is allowed (it names the model)
                record["stage"] = "build_error_unhandled"
                results.append(record)
                print(f"[{case_id}] mutant dbt run failed (build error) — unhandled")
                continue
            cur = _snapshot_tables()
            div = _divergent_models(parent_snap, cur) if cur else []
            if not div:
                record["stage"] = "missed_detection"
                results.append(record)
                print(f"[{case_id}] missed_detection (true: {rel})")
                continue

            first = div[0]
            record["localized"] = first
            # candidates: first divergent model + its direct upstreams, cap 3
            candidates = ([first] + UPSTREAM.get(first, []))[:3]

            success = False
            for cand in candidates:
                cand_path = REPO / MODEL_FILES[cand]
                cand_src = cand_path.read_text(encoding="utf-8")
                divergence = _divergence_sample(parent_snap, cur, first)
                fixed = _attempt_patch(cand, cand_src, divergence)
                if not fixed:
                    record["attempts"].append([cand, False])
                    continue
                cand_path.write_text(fixed, encoding="utf-8")
                ok2, _ = _dbt("run")
                ver = False
                if ok2:
                    snap2 = _snapshot_tables()
                    ver = bool(snap2) and not _divergent_models(parent_snap, snap2)
                record["attempts"].append([cand, ver])
                if ver:
                    success = True
                    record["repaired_model"] = cand
                    break
                cand_path.write_text(cand_src, encoding="utf-8")  # revert this attempt

            if not success:
                record["stage"] = "repair_failed"
                results.append(record)
                print(f"[{case_id}] repair_failed (true: {rel}, localized: {first})")
                continue

            record["loop_success"] = True
            gt, _ = _dbt("build")          # held-out ground truth
            record["ground_truth"] = gt
            record["stage"] = "success" if gt else "false_success"
            results.append(record)
            print(f"[{case_id}] loop=SUCCESS gt={gt} repaired={record['repaired_model']} "
                  f"(true: {rel})")
        finally:
            for r2, src in parents.items():
                (REPO / r2).write_text(src, encoding="utf-8")

    from collections import Counter
    n = len(results)
    gt = sum(r["ground_truth"] for r in results)
    fs = sum(1 for r in results if r["loop_success"] and not r["ground_truth"])
    det = sum(1 for r in results if r["localized"] or r["stage"] == "build_error_unhandled")
    loc = sum(1 for r in results
              if r["localized"] and MODEL_FILES.get(r["localized"]) == r["true_model"])
    stages = Counter(r["stage"] for r in results)
    print("\n" + "=" * 70)
    print(f"TRANSFER RUNG 2  jaffle_shop_duckdb (dbt SQL)  n={n}")
    print("=" * 70)
    print(f"  detection            : {det}/{n}")
    print(f"  localized == true    : {loc}/{n}")
    print(f"  ground-truth success : {gt}/{n} = {gt/n:.0%}")
    print(f"  false successes      : {fs}")
    print(f"  stage attrition      : {dict(stages)}")
    band = ("GREEN" if (gt / n >= 0.25 and fs == 0) else
            "YELLOW" if ((gt / n >= 0.10 and fs == 0) or (gt / n >= 0.25 and fs <= 1)) else
            "RED")
    print(f"  precommit            : {band}")
    OUT.write_text(json.dumps({"model": MODEL, "repo": "jaffle_shop_duckdb",
                               "results": results}, indent=2), encoding="utf-8")
    print(f"\nResults: {OUT}")


if __name__ == "__main__":
    main()
