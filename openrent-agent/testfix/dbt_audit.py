"""
testfix/dbt_audit.py — DBT Localization Feature-Density Audit

Pre-experiment for the accumulated-learning loop (Phase 2).
See DBTAUDIT-precommit.md for the pre-committed decision criterion.

Audits two candidate-pool resolutions:
  L1 — model level    (5 models; DAG-order baseline; expected: ceiling)
  L2 — expression level (SQL expressions within the localized model; the question)

Decision criterion (pre-committed):
  GREEN  ≥60% of detectable mutations uniquely identifiable by column divergence
  YELLOW 40–59%
  RED    <40% — column divergence insufficient; add feature before building loop

Run from openrent-agent/:
    python testfix/dbt_audit.py [--verbose]
"""

import argparse
import json
import subprocess
from pathlib import Path

REPO = Path("D:/transfer-rung1/jaffle_shop_duckdb")
DB   = REPO / "jaffle_shop.duckdb"
OUT  = Path(__file__).resolve().parent / "dbt_audit_results.json"

# ── DAG topology ──────────────────────────────────────────────────────────────
DAG_ORDER = ["stg_customers", "stg_orders", "stg_payments", "customers", "orders"]
MODEL_FILES = {
    "stg_customers": "models/staging/stg_customers.sql",
    "stg_orders":    "models/staging/stg_orders.sql",
    "stg_payments":  "models/staging/stg_payments.sql",
    "customers":     "models/customers.sql",
    "orders":        "models/orders.sql",
}
DAG_POS = {m: i for i, m in enumerate(DAG_ORDER)}
N_DOWNSTREAM = {  # hard-coded for this 5-model DAG
    "stg_customers": 1,
    "stg_orders":    2,
    "stg_payments":  2,
    "customers":     0,
    "orders":        0,
}
# model file path → model name
FILE_TO_MODEL = {v: k for k, v in MODEL_FILES.items()}

# ── Expression candidates (hard-coded for jaffle_shop; honest for a known schema)
# Each expression carries: which output columns it feeds, whether it is a join
# or aggregate, and its approximate source line.
EXPRESSION_CANDIDATES: dict[str, list[dict]] = {
    "models/customers.sql": [
        {"expr_id": "e_co_join",    "desc": "customer_orders join condition (L62)",
         "feeds_cols": frozenset(["first_order", "most_recent_order", "number_of_orders"]),
         "is_join": True,  "is_agg": False, "line": 62},
        {"expr_id": "e_cp_join",    "desc": "customer_payments join condition (L65)",
         "feeds_cols": frozenset(["customer_lifetime_value"]),
         "is_join": True,  "is_agg": False, "line": 65},
        {"expr_id": "e_inner_join", "desc": "customer_payments inner join (L42)",
         "feeds_cols": frozenset(["customer_lifetime_value"]),
         "is_join": True,  "is_agg": False, "line": 42},
        {"expr_id": "e_min",        "desc": "min(order_date) (L24)",
         "feeds_cols": frozenset(["first_order"]),
         "is_join": False, "is_agg": True,  "line": 24},
        {"expr_id": "e_max",        "desc": "max(order_date) (L25)",
         "feeds_cols": frozenset(["most_recent_order"]),
         "is_join": False, "is_agg": True,  "line": 25},
        {"expr_id": "e_count",      "desc": "count(order_id) (L26)",
         "feeds_cols": frozenset(["number_of_orders"]),
         "is_join": False, "is_agg": True,  "line": 26},
        {"expr_id": "e_sum",        "desc": "sum(amount) in customer_payments (L37)",
         "feeds_cols": frozenset(["customer_lifetime_value"]),
         "is_join": False, "is_agg": True,  "line": 37},
    ],
    "models/orders.sql": [
        {"expr_id": "e_join",       "desc": "order_payments join condition (L52)",
         "feeds_cols": frozenset(["credit_card_amount", "coupon_amount",
                                  "bank_transfer_amount", "gift_card_amount", "amount"]),
         "is_join": True,  "is_agg": False, "line": 52},
        {"expr_id": "e_case",       "desc": "CASE WHEN payment_method else 0 (L21)",
         "feeds_cols": frozenset(["credit_card_amount", "coupon_amount",
                                  "bank_transfer_amount", "gift_card_amount"]),
         "is_join": False, "is_agg": True,  "line": 21},
        {"expr_id": "e_total",      "desc": "sum(amount) as total_amount (L24)",
         "feeds_cols": frozenset(["amount"]),
         "is_join": False, "is_agg": True,  "line": 24},
    ],
    "models/staging/stg_payments.sql": [
        {"expr_id": "e_div",        "desc": "amount / 100 as amount (L19)",
         "feeds_cols": frozenset(["amount"]),
         "is_join": False, "is_agg": False, "line": 19},
    ],
    # Staging models with only renames: no discriminating expressions.
    "models/staging/stg_customers.sql": [],
    "models/staging/stg_orders.sql": [],
}

# ── Mutation set ──────────────────────────────────────────────────────────────
# true_expr_id: the expression in EXPRESSION_CANDIDATES that was mutated.
# None for build-error cases.
MUTATIONS = [
    # — original transfer2 mutations —
    {"case_id": "d001", "model": "models/customers.sql", "lineno": 65,
     "operator": "eq_to_neq",
     "original_line": "        on  customers.customer_id = customer_payments.customer_id\n",
     "mutated_line":  "        on  customers.customer_id != customer_payments.customer_id\n",
     "true_expr_id": "e_cp_join"},
    {"case_id": "d003", "model": "models/customers.sql", "lineno": 62,
     "operator": "eq_to_neq",
     "original_line": "        on customers.customer_id = customer_orders.customer_id\n",
     "mutated_line":  "        on customers.customer_id != customer_orders.customer_id\n",
     "true_expr_id": "e_co_join"},
    {"case_id": "d002", "model": "models/orders.sql", "lineno": 52,
     "operator": "eq_to_neq",
     "original_line": "        on orders.order_id = order_payments.order_id\n",
     "mutated_line":  "        on orders.order_id != order_payments.order_id\n",
     "true_expr_id": "e_join"},
    {"case_id": "d004", "model": "models/orders.sql", "lineno": 1,
     "operator": "eq_to_neq_jinja",
     "original_line": "{% set payment_methods = ['credit_card', 'coupon', 'bank_transfer', 'gift_card'] %}\n",
     "mutated_line":  "{% set payment_methods != ['credit_card', 'coupon', 'bank_transfer', 'gift_card'] %}\n",
     "true_expr_id": None},   # Expected: build_error (Jinja syntax)

    # — customers.sql: aggregate mutations —
    {"case_id": "d_c01", "model": "models/customers.sql", "lineno": 24,
     "operator": "min_to_max",
     "original_line": "        min(order_date) as first_order,\n",
     "mutated_line":  "        max(order_date) as first_order,\n",
     "true_expr_id": "e_min"},
    {"case_id": "d_c02", "model": "models/customers.sql", "lineno": 25,
     "operator": "max_to_min",
     "original_line": "        max(order_date) as most_recent_order,\n",
     "mutated_line":  "        min(order_date) as most_recent_order,\n",
     "true_expr_id": "e_max"},
    {"case_id": "d_c03", "model": "models/customers.sql", "lineno": 26,
     "operator": "count_to_sum",
     "original_line": "        count(order_id) as number_of_orders\n",
     "mutated_line":  "        sum(order_id) as number_of_orders\n",
     "true_expr_id": "e_count"},
    {"case_id": "d_c04", "model": "models/customers.sql", "lineno": 37,
     "operator": "sum_to_avg",
     "original_line": "        sum(amount) as total_amount\n",
     "mutated_line":  "        avg(amount) as total_amount\n",
     "true_expr_id": "e_sum"},
    {"case_id": "d_c05", "model": "models/customers.sql", "lineno": 42,
     "operator": "eq_to_neq",
     "original_line": "         payments.order_id = orders.order_id\n",
     "mutated_line":  "         payments.order_id != orders.order_id\n",
     "true_expr_id": "e_inner_join"},

    # — orders.sql: mutations —
    {"case_id": "d_o01", "model": "models/orders.sql", "lineno": 21,
     "operator": "else0_to_else1",
     "original_line": "        sum(case when payment_method = '{{ payment_method }}' then amount else 0 end) as {{ payment_method }}_amount,\n",
     "mutated_line":  "        sum(case when payment_method = '{{ payment_method }}' then amount else 1 end) as {{ payment_method }}_amount,\n",
     "true_expr_id": "e_case"},
    {"case_id": "d_o02", "model": "models/orders.sql", "lineno": 24,
     "operator": "sum_to_avg",
     "original_line": "        sum(amount) as total_amount\n",
     "mutated_line":  "        avg(amount) as total_amount\n",
     "true_expr_id": "e_total"},

    # — stg_payments.sql: staging mutation (amount scale factor inverted) —
    {"case_id": "d_s01", "model": "models/staging/stg_payments.sql", "lineno": 19,
     "operator": "div_to_mul",
     "original_line": "        amount / 100 as amount\n",
     "mutated_line":  "        amount * 100 as amount\n",
     "true_expr_id": "e_div"},
]


# ── dbt helpers ───────────────────────────────────────────────────────────────

def _dbt(cmd: str) -> tuple[bool, str]:
    r = subprocess.run(
        ["dbt", cmd, "--no-use-colors"],
        capture_output=True, text=True, cwd=REPO, timeout=300, shell=True,
    )
    return r.returncode == 0, r.stdout + r.stderr


def _snapshot() -> dict | None:
    """Read all model tables as both row-sets and per-column value sets."""
    try:
        import duckdb
        con = duckdb.connect(str(DB), read_only=True)
        out = {}
        for m in DAG_ORDER:
            try:
                rows = con.execute(f'SELECT * FROM "{m}"').fetchall()
                desc = con.execute(f'SELECT * FROM "{m}" LIMIT 0').description
                cols = [d[0] for d in desc]
                out[m] = {
                    "cols": cols,
                    "rows": sorted(repr(r) for r in rows),
                    "rows_raw": rows,
                }
            except Exception as e:
                out[m] = {"error": str(e)}
        con.close()
        return out
    except Exception as e:
        return None


def _divergent_models(parent: dict, current: dict) -> list[str]:
    """Models whose row-set or schema differs from parent, in DAG order."""
    div = []
    for m in DAG_ORDER:
        pm, cm = parent.get(m), current.get(m)
        if pm is None or cm is None:
            continue
        if "error" in pm or "error" in cm:
            continue
        if pm["rows"] != cm["rows"] or pm["cols"] != cm["cols"]:
            div.append(m)
    return div


def _divergent_columns(parent: dict, current: dict, model: str) -> list[str]:
    """Which output columns of `model` have different value distributions."""
    pm = parent.get(model, {})
    cm = current.get(model, {})
    if not pm or not cm or "error" in pm or "error" in cm:
        return []
    if pm["cols"] != cm["cols"]:
        return list(pm["cols"]) or list(cm["cols"])
    cols = pm["cols"]
    diverged = []
    for i, col in enumerate(cols):
        p_vals = sorted(str(r[i]) if i < len(r) else "" for r in pm["rows_raw"])
        c_vals = sorted(str(r[i]) if i < len(r) else "" for r in cm["rows_raw"])
        if p_vals != c_vals:
            diverged.append(col)
    return diverged


def _row_count_changed(parent: dict, current: dict, model: str) -> bool:
    """Did the number of output rows change for this model?"""
    pm = parent.get(model, {})
    cm = current.get(model, {})
    if not pm or not cm or "error" in pm or "error" in cm:
        return False
    return len(pm["rows_raw"]) != len(cm["rows_raw"])


# ── Expression discriminability ───────────────────────────────────────────────

def _candidate_expressions(model_rel: str) -> list[dict]:
    return EXPRESSION_CANDIDATES.get(model_rel, [])


def _discriminability(diverged_cols: list[str], model_rel: str) -> dict:
    """
    Given a set of diverged output columns and a model, score each candidate
    expression by how well it explains the observation.

    exact_match: expressions whose feeds_cols == diverged_cols exactly.
    superset_match: expressions that feed ALL diverged cols (may feed more).
    any_overlap: expressions that feed at least one diverged col.

    unique_exact: True if exactly one expression has exact_match.
    unique_superset: True if exactly one expression has the SMALLEST superset.
    """
    div_set = frozenset(diverged_cols)
    candidates = _candidate_expressions(model_rel)

    exact, superset, overlap = [], [], []
    for e in candidates:
        fc = e["feeds_cols"]
        if fc == div_set:
            exact.append(e["expr_id"])
        if div_set.issubset(fc):
            superset.append(e["expr_id"])
        if div_set & fc:
            overlap.append(e["expr_id"])

    # Smallest-superset: among superset matches, find minimum feeds_cols size
    min_size = min((len(e["feeds_cols"]) for e in candidates
                    if div_set.issubset(e["feeds_cols"])), default=None)
    min_superset = [e["expr_id"] for e in candidates
                    if div_set.issubset(e["feeds_cols"])
                    and len(e["feeds_cols"]) == min_size]

    return {
        "n_candidates": len(candidates),
        "exact_match": exact,
        "superset_match": superset,
        "min_superset": min_superset,
        "any_overlap": overlap,
        "unique_exact": len(exact) == 1,
        "unique_superset": len(min_superset) == 1,
        "n_narrowed": len(overlap),            # remaining after column narrowing
        "narrowing_ratio": (
            round(len(overlap) / len(candidates), 3) if candidates else None
        ),
    }


# ── Per-mutation audit ────────────────────────────────────────────────────────

def _audit_mutation(mut: dict, parent_snap: dict, parent_srcs: dict,
                    verbose: bool) -> dict:
    case_id = mut["case_id"]
    rel     = mut["model"]
    path    = REPO / rel
    lineno  = mut["lineno"]

    rec: dict = {
        "case_id": case_id,
        "true_model_rel": rel,
        "true_model":     FILE_TO_MODEL.get(rel, rel),
        "operator": mut["operator"],
        "true_expr_id": mut["true_expr_id"],
        "stage": None,
        # L1 model-level
        "l1_first_divergent": None,
        "l1_dag_correct": None,
        "l1_divergent_models": [],
        "l1_features": {},
        # L2 expression-level
        "l2_diverged_cols": {},
        "l2_discriminability": {},
        "l2_unique_exact": None,
        "l2_unique_superset": None,
        "l2_true_in_exact": None,
        "l2_true_in_superset": None,
        "l2_narrowed_to": None,
    }

    # Validate line content
    parent_src = parent_srcs[rel]
    lines = parent_src.splitlines(keepends=True)
    if lineno - 1 >= len(lines):
        rec["stage"] = "line_out_of_range"
        print(f"[{case_id}] SKIP: line {lineno} out of range for {rel}")
        return rec
    if lines[lineno - 1] != mut["original_line"]:
        rec["stage"] = "line_mismatch"
        print(f"[{case_id}] SKIP: line mismatch at L{lineno}")
        if verbose:
            print(f"  expected: {mut['original_line']!r}")
            print(f"  found:    {lines[lineno-1]!r}")
        return rec

    # Apply mutation
    lines[lineno - 1] = mut["mutated_line"]
    path.write_text("".join(lines), encoding="utf-8")

    try:
        ok, dbt_out = _dbt("run")
        if not ok:
            rec["stage"] = "build_error"
            print(f"[{case_id}] build_error (operator={mut['operator']})")
            return rec

        cur_snap = _snapshot()
        if cur_snap is None:
            rec["stage"] = "snapshot_failed"
            print(f"[{case_id}] snapshot_failed")
            return rec

        div_models = _divergent_models(parent_snap, cur_snap)
        if not div_models:
            rec["stage"] = "missed_detection"
            print(f"[{case_id}] missed_detection (no table change observed)")
            return rec

        rec["stage"] = "detected"
        rec["l1_divergent_models"] = div_models
        first_div = div_models[0]
        rec["l1_first_divergent"] = first_div
        true_model = FILE_TO_MODEL.get(rel, rel)
        rec["l1_dag_correct"] = (first_div == true_model)
        rec["l2_row_count_changed"] = {
            m: _row_count_changed(parent_snap, cur_snap, m) for m in div_models
        }

        # ── L1 model-level features ───────────────────────────────────────────
        features_per_model = {}
        for m in DAG_ORDER:
            is_first_div = (m == first_div)
            dag_dist = DAG_POS[m] - DAG_POS[first_div]
            n_div_downstream = sum(
                1 for d in div_models
                if DAG_POS[d] > DAG_POS[m]
            )
            model_file = MODEL_FILES[m]
            # Does this model's file path appear in the mutation diff text?
            name_in_diff = (
                m in mut["original_line"] + mut["mutated_line"] or
                model_file.split("/")[-1].replace(".sql", "") in
                    mut["original_line"] + mut["mutated_line"]
            )
            features_per_model[m] = {
                "dag_first_divergent": is_first_div,
                "dag_distance":        dag_dist,
                "name_in_diff":        name_in_diff,
                "downstream_div_count": n_div_downstream,
                "n_downstream":        N_DOWNSTREAM[m],
                "is_diverged":         m in div_models,
            }
        rec["l1_features"] = features_per_model

        # ── L2 column/expression-level features (on the first-divergent model) -
        div_cols_per_model = {}
        for dm in div_models:
            div_cols_per_model[dm] = _divergent_columns(parent_snap, cur_snap, dm)
        rec["l2_diverged_cols"] = div_cols_per_model

        # Primary analysis: on the first-divergent (= localized) model
        loc_div_cols = div_cols_per_model.get(first_div, [])
        disc = _discriminability(loc_div_cols, MODEL_FILES.get(first_div, first_div))
        rec["l2_discriminability"] = disc
        rec["l2_unique_exact"]     = disc["unique_exact"]
        rec["l2_unique_superset"]  = disc["unique_superset"]
        rec["l2_narrowed_to"]      = disc["n_narrowed"]

        # Is the true expression found by exact match?
        true_expr = mut["true_expr_id"]
        if true_expr:
            rec["l2_true_in_exact"]     = true_expr in disc["exact_match"]
            rec["l2_true_in_superset"]  = true_expr in disc["superset_match"]

        tag = ("UNIQUE_EXACT" if disc["unique_exact"] else
               "UNIQUE_SUPERSET" if disc["unique_superset"] else
               f"AMBIGUOUS({disc['n_narrowed']} candidates)")
        print(f"[{case_id}] detected | L1={first_div} ({'OK' if rec['l1_dag_correct'] else 'WRONG'}) "
              f"| L2 div_cols={loc_div_cols} | {tag}")

    finally:
        path.write_text(parent_src, encoding="utf-8")

    return rec


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    # Load parent sources and build parent snapshot
    mut_models = {m["model"] for m in MUTATIONS}
    parent_srcs = {rel: (REPO / rel).read_text(encoding="utf-8")
                   for rel in mut_models}

    print("Building parent snapshots (dbt run on clean repo)...")
    ok, out = _dbt("run")
    if not ok:
        print("ERROR: parent dbt run failed — repo must be clean before audit")
        print(out[-2000:])
        return
    parent_snap = _snapshot()
    if parent_snap is None:
        print("ERROR: could not snapshot parent tables")
        return
    print(f"  Parent built. Models: {[m for m in DAG_ORDER if 'error' not in parent_snap.get(m,{})]}\n")

    results = []
    for mut in MUTATIONS:
        rec = _audit_mutation(mut, parent_snap, parent_srcs, args.verbose)
        results.append(rec)

    # ── Report ────────────────────────────────────────────────────────────────
    sep = "=" * 72
    print(f"\n{sep}")
    print("DBTAUDIT — Feature Density Results")
    print(sep)

    detected = [r for r in results if r["stage"] == "detected"]
    build_err = [r for r in results if r["stage"] == "build_error"]
    missed    = [r for r in results if r["stage"] == "missed_detection"]
    skipped   = [r for r in results if r["stage"] not in ("detected", "build_error",
                                                           "missed_detection")]
    n = len(results)
    nd = len(detected)

    print(f"\nn total    : {n}")
    print(f"detected   : {nd}  (build_error={len(build_err)}, "
          f"missed={len(missed)}, other={len(skipped)})")

    # L1: model-level
    l1_correct = sum(1 for r in detected if r["l1_dag_correct"])
    print(f"\nL1 model-level localization (DAG-order baseline):")
    print(f"  top-1 correct : {l1_correct}/{nd} = {l1_correct/nd:.0%}" if nd else "  n=0")
    print(f"  (expected: 100% — structural ceiling for single-model mutations)")

    # L1 feature signal (do any model-level features separate true from others?)
    # A feature "carries signal" if it takes a distinct value for the true model
    # that no other model has (i.e., it uniquely identifies the true model).
    print(f"\n  L1 feature discriminability (does each feature alone identify true model?):")
    feature_names = ["dag_first_divergent", "dag_distance", "name_in_diff",
                     "downstream_div_count", "n_downstream"]
    for feat in feature_names:
        perfect = 0
        for r in detected:
            true_m = r["true_model"]
            feat_vals = {m: r["l1_features"][m][feat]
                         for m in DAG_ORDER if m in r["l1_features"]}
            true_val = feat_vals.get(true_m)
            # Is this value unique to the true model?
            if sum(1 for v in feat_vals.values() if v == true_val) == 1:
                perfect += 1
        print(f"  {feat:<28}: uniquely identifies true model in {perfect}/{nd}")

    # L2: expression-level
    print(f"\nL2 expression-level (column-divergence discriminability):")
    unique_exact     = sum(1 for r in detected if r["l2_unique_exact"])
    unique_superset  = sum(1 for r in detected if r["l2_unique_superset"])
    true_in_exact    = sum(1 for r in detected
                           if r["l2_true_in_exact"] is True)
    true_in_superset = sum(1 for r in detected
                           if r["l2_true_in_superset"] is True)

    pct_exact = unique_exact / nd if nd else 0
    print(f"  unique exact match    : {unique_exact}/{nd} = {pct_exact:.0%}")
    print(f"  unique superset match : {unique_superset}/{nd}")
    print(f"  true expr in exact    : {true_in_exact}/{nd}  (recall @ unique)")
    print(f"  true expr in superset : {true_in_superset}/{nd}")

    # Per-case table
    print("\n  {0:<10} {1:<18} {2:<16} {3:>6} {4:>5} {5:>6}  L2 discriminability".format(
        "case_id", "stage", "first_div", "L1_ok", "n_div", "row_ct"))
    print("  " + "-" * 100)
    for r in results:
        fd = r.get("l1_first_divergent", "")
        cols = r.get("l2_diverged_cols", {}).get(fd, [])
        n_div = len(cols) if cols else 0
        row_ct = r.get("l2_row_count_changed", {}).get(fd, False)
        if r["l2_unique_exact"]:
            disc_str = "UNIQUE_EXACT  -> " + str(r["l2_discriminability"].get("exact_match", []))
        elif r["l2_unique_superset"]:
            disc_str = "UNIQUE_SUPER  -> " + str(r["l2_discriminability"].get("min_superset", []))
        elif r["stage"] == "detected":
            disc_str = "AMBIGUOUS({} remaining)".format(r["l2_narrowed_to"])
        else:
            disc_str = r["stage"]
        l1_ok = ("YES" if r["l1_dag_correct"] else
                 "NO" if r["l1_dag_correct"] is False else "-")
        print("  {:<10} {:<18} {:<16} {:>6}  {:>4} {:>6}   {}".format(
            r["case_id"], r["stage"], str(fd), l1_ok, n_div, str(row_ct), disc_str))

    # Extended analysis: row_count_changed resolves join-explosion ambiguity
    print("\n  Extended analysis (+ row_count_changed feature):")
    print("  row_count_changed=True  -> outer-join explosion: filter to outer-join candidates")
    print("  row_count_changed=False -> aggregate/inner-CTE: use superset match")
    n_unique_ext = 0
    for r in detected:
        if r["l2_unique_exact"]:
            n_unique_ext += 1
            continue
        fd = r.get("l1_first_divergent", "")
        row_ct = r.get("l2_row_count_changed", {}).get(fd, False)
        model_rel = MODEL_FILES.get(fd, fd)
        candidates = _candidate_expressions(model_rel)
        if row_ct:
            outer_joins = [e for e in candidates
                           if e["is_join"] and e["expr_id"] in ("e_co_join", "e_cp_join", "e_join")]
            unique_ext = (len(outer_joins) == 1)
            tc = r["true_expr_id"]
            in_class = any(e["expr_id"] == tc for e in outer_joins) if tc else None
            tag = ("UNIQUE" if unique_ext else "AMBIGUOUS({} outer joins)".format(len(outer_joins)))
            print("    {}: row_ct=True, {}, true_in_class={}".format(r["case_id"], tag, in_class))
        else:
            unique_ext = r["l2_unique_superset"]
            if not unique_ext:
                disc = r["l2_discriminability"]
                tc = r["true_expr_id"]
                cols = r.get("l2_diverged_cols", {}).get(fd, [])
                print("    {}: row_ct=False, STILL_AMBIGUOUS({} candidates), cols={}, true={}".format(
                    r["case_id"], disc.get("n_narrowed", "?"), cols, tc))
        if unique_ext:
            n_unique_ext += 1

    pct_ext = n_unique_ext / nd if nd else 0
    print("  Extended unique: {}/{} = {:.0%}".format(n_unique_ext, nd, pct_ext))

    # Irreducibly ambiguous residual
    still_ambiguous = [r for r in detected
                       if not r["l2_unique_exact"]
                       and not r.get("l2_discriminability", {}).get("unique_superset")]
    if still_ambiguous:
        print("\n  Irreducibly ambiguous ({}) -- repair context needed to break tie:".format(
            len(still_ambiguous)))
        for r in still_ambiguous:
            disc = r["l2_discriminability"]
            fd = r.get("l1_first_divergent", "")
            row_ct = r.get("l2_row_count_changed", {}).get(fd, False)
            model_rel = MODEL_FILES.get(fd, fd)
            cands = _candidate_expressions(model_rel)
            if row_ct:
                remaining = [e for e in cands if e["is_join"] and e["expr_id"] in ("e_co_join", "e_cp_join")]
            else:
                remaining = [e for e in cands if e["expr_id"] in disc.get("any_overlap", [])]
            tc = r["true_expr_id"]
            cols = r.get("l2_diverged_cols", {}).get(fd, [])
            in_rem = tc in [e["expr_id"] for e in remaining] if tc else None
            print("    {}: {} candidates after narrowing, true_in_remaining={}, cols={}".format(
                r["case_id"], len(remaining), in_rem, cols))

    # VERDICT
    band_exact = ("GREEN"  if nd and pct_exact >= 0.60 else
                  "YELLOW" if nd and pct_exact >= 0.40 else
                  "RED")
    band_ext   = ("GREEN"  if nd and pct_ext >= 0.60 else
                  "YELLOW" if nd and pct_ext >= 0.40 else
                  "RED")
    print("\n" + sep)
    print("VERDICT (exact-match, pre-committed): {}  ({}/{} = {:.0%})".format(
        band_exact, unique_exact, nd, pct_exact))
    print("VERDICT (+ row_count_changed):        {}  ({}/{} = {:.0%})".format(
        band_ext, n_unique_ext, nd, pct_ext))
    if band_ext == "GREEN":
        print("Signal sufficient. Proceed to Phase 2 (accumulated-learning loop).")
    elif band_ext == "YELLOW":
        print("Borderline. Add column_lineage_rank feature and rerun before Phase 2.")
    else:
        print("Insufficient signal. Do NOT build Phase 2 loop.")
    print(sep)

    # Save results
    out_data = {
        "n_total": n,
        "n_detected": nd,
        "n_build_error": len(build_err),
        "n_missed": len(missed),
        "l1_model_top1": l1_correct,
        "l1_model_top1_pct": round(l1_correct / nd, 3) if nd else None,
        "l2_unique_exact": unique_exact,
        "l2_unique_exact_pct": round(pct_exact, 3),
        "l2_unique_superset": unique_superset,
        "l2_true_in_exact": true_in_exact,
        "l2_true_in_superset": true_in_superset,
        "verdict_exact": band_exact,
        "verdict_ext": band_ext,
        "results": results,
    }
    # Convert frozensets to lists for JSON serialisation
    def _prep(obj):
        if isinstance(obj, frozenset):
            return sorted(obj)
        if isinstance(obj, dict):
            return {k: _prep(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_prep(x) for x in obj]
        return obj
    OUT.write_text(json.dumps(_prep(out_data), indent=2), encoding="utf-8")
    print(f"\nResults: {OUT}")


if __name__ == "__main__":
    main()
