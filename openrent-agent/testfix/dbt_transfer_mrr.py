"""
dbt_transfer_mrr.py -- Phase 2b transfer run on dbt-labs/mrr-playbook.

Transfer claim:
  diff_kind_match (computed by diff_parser.classify_diff_kind from real SQL diffs)
  improves localization on an unseen dbt project without re-tuning.

Pre-committed validity conditions (PHASE2B-TRANSFER-precommit.md):
  1. diff_kind parsed mechanically from SQL diff hunk. DONE.
  2. Target has >=1 ambiguous same-context-key pair. CONFIRMED: customer_revenue_by_month.sql.
  3. At least one ambiguous pair has mixed diff_kind. CONFIRMED: agg + join candidates.

Structural note: mrr-playbook uses CASCADE ambiguity (agg feeds the join condition),
vs jaffle_shop_duckdb's PARALLEL ambiguity (agg and join independently feed same col).
This is a genuine structural difference from the training project.

Verdict bands (delta threshold 0.05):
  GREEN  : MRR_2b > MRR_freq + 0.05  AND  > MRR_static + 0.05
  YELLOW : MRR_2b > MRR_static + 0.05  AND  <= MRR_freq + 0.05
  RED    : MRR_2b <= MRR_static + 0.05
"""

import json
import random
import pathlib
from typing import Dict, List, Tuple

import numpy as np
from diff_parser import classify_diff_kind

HERE = pathlib.Path(__file__).resolve().parent
OUT  = HERE / "dbt_transfer_mrr_results.json"

DELTA       = 0.05
N_ROUNDS    = 4
ROUND_SEEDS = [52, 53, 54, 55]

# ---- expression candidates ----
# Models from D:\transfer-rung2-mrr  (dbt-labs/mrr-playbook)
# Each candidate: expr_id, feeds_cols, is_agg, is_join, line

CRM_MODEL = "models/customer_revenue_by_month.sql"
MRR_MODEL = "models/mrr.sql"
CCM_MODEL = "models/customer_churn_month.sql"

# Final output columns per model (for n_div_norm)
_MODEL_N_COLS = {
    CRM_MODEL: 8,   # date_month, customer_id, mrr, is_active,
                    # first_active_month, last_active_month, is_first_month, is_last_month
    MRR_MODEL: 14,  # id + all crm cols + previous_month_is_active, previous_month_mrr,
                    #   mrr_change, change_category, renewal_amount
    CCM_MODEL: 8,   # same output shape as crm (date_month, customer_id, mrr, ...)
}

# CRM candidates
_CRM_SPINE_COLS = frozenset([
    "date_month", "mrr", "is_active",
    "first_active_month", "last_active_month",
    "is_first_month", "is_last_month",
])
_CRM_VALUE_COLS = frozenset([
    "mrr", "is_active",
    "first_active_month", "last_active_month",
    "is_first_month", "is_last_month",
])

EXPRESSION_CANDIDATES = {
    CRM_MODEL: [
        # customers CTE: date spine aggregates
        {"expr_id": "e_min_start",
         "feeds_cols": _CRM_SPINE_COLS,
         "is_agg": True,  "is_join": False, "line": 18},
        {"expr_id": "e_max_end",
         "feeds_cols": _CRM_SPINE_COLS,
         "is_agg": True,  "is_join": False, "line": 19},
        # customer_months CTE: inner join months (spine join)
        {"expr_id": "e_cm_join",
         "feeds_cols": _CRM_SPINE_COLS,
         "is_agg": False, "is_join": True,  "line": 37},
        # joined CTE: left join subscription_periods (value join)
        {"expr_id": "e_sub_join",
         "feeds_cols": _CRM_VALUE_COLS,
         "is_agg": False, "is_join": True,  "line": 56},
        # joined CTE: coalesce(monthly_amount, 0) as mrr
        {"expr_id": "e_coalesce_mrr",
         "feeds_cols": _CRM_VALUE_COLS,
         "is_agg": False, "is_join": False, "line": 52},
    ],
    MRR_MODEL: [
        # mrr_with_changes CTE: lag(mrr) window function
        {"expr_id": "e_lag_mrr",
         "feeds_cols": frozenset(["previous_month_mrr", "mrr_change",
                                   "change_category", "renewal_amount"]),
         "is_agg": False, "is_join": False, "line": 23},
        # mrr_with_changes CTE: arithmetic mrr - previous_month_mrr
        {"expr_id": "e_mrr_change",
         "feeds_cols": frozenset(["mrr_change", "change_category"]),
         "is_agg": False, "is_join": False, "line": 27},
        # final CTE: least(mrr, previous_month_mrr)
        {"expr_id": "e_renewal",
         "feeds_cols": frozenset(["renewal_amount"]),
         "is_agg": False, "is_join": False, "line": 53},
    ],
    CCM_MODEL: [
        # joined CTE: dateadd(month, 1, date_month) as date_month
        {"expr_id": "e_ccm_date",
         "feeds_cols": frozenset(["date_month"]),
         "is_agg": False, "is_join": False, "line": 11},
    ],
}

# ---- synthetic diff hunks (from actual mrr-playbook SQL) ----
# Constructed from D:\transfer-rung2-mrr\models\*.sql  (git diff -U2 style)
# These are the real hunks that classify_diff_kind will parse.

MRR_DIFFS = {
    # CRM01: customers CTE -- mutate min(start_date) [agg]
    "m_crm01": """\
@@ -16,5 +16,5 @@
     select
         customer_id,
-        date_trunc('month', min(start_date)) as date_month_start,
+        date_trunc('month', min(start_date + 1)) as date_month_start,
         date_trunc('month', max(end_date)) as date_month_end
""",
    # CRM02: customers CTE -- mutate max(end_date) [agg]
    "m_crm02": """\
@@ -17,5 +17,5 @@
         customer_id,
         date_trunc('month', min(start_date)) as date_month_start,
-        date_trunc('month', max(end_date)) as date_month_end
+        date_trunc('month', max(end_date + 1)) as date_month_end

     from subscription_periods
""",
    # CRM03: customer_months CTE -- mutate inner join >= condition [join]
    # JOIN keyword is on line 37 (context); changed line = ON condition
    "m_crm03": """\
@@ -37,6 +37,6 @@
     inner join months
         -- all months after start date
-        on  months.date_month >= customers.date_month_start
+        on  months.date_month > customers.date_month_start
         -- and before end date
         and months.date_month < customers.date_month_end
""",
    # CRM04: joined CTE -- mutate left join subscription_periods ON condition [join]
    # JOIN keyword is on line 56 (context); changed line = first ON clause line
    "m_crm04": """\
@@ -56,6 +56,6 @@
     left join subscription_periods
-        on customer_months.customer_id = subscription_periods.customer_id
+        on customer_months.customer_id != subscription_periods.customer_id
         -- month is after a subscription start date
         and customer_months.date_month >= subscription_periods.start_date
""",
    # CRM05: joined CTE -- mutate coalesce default value [unknown]
    "m_crm05": """\
@@ -49,5 +49,5 @@
         customer_months.date_month,
         customer_months.customer_id,
-        coalesce(subscription_periods.monthly_amount, 0) as mrr
+        coalesce(subscription_periods.monthly_amount, 1) as mrr

     from customer_months
""",
    # MRR01: mrr_with_changes CTE -- mutate lag window offset [unknown]
    "m_mrr01": """\
@@ -21,5 +21,5 @@
         coalesce(
-            lag(mrr) over (partition by customer_id order by date_month),
+            lag(mrr, 2) over (partition by customer_id order by date_month),
             0
         ) as previous_month_mrr,
""",
    # MRR02: mrr_with_changes CTE -- mutate arithmetic subtraction [arithmetic]
    "m_mrr02": """\
@@ -25,5 +25,5 @@
         ) as previous_month_mrr,

-        mrr - previous_month_mrr as mrr_change
+        mrr - previous_month_mrr - 1 as mrr_change

     from unioned
""",
    # MRR03: final CTE -- mutate least() to greatest() [unknown]
    "m_mrr03": """\
@@ -51,5 +51,5 @@

-        least(mrr, previous_month_mrr) as renewal_amount
+        greatest(mrr, previous_month_mrr) as renewal_amount

     from mrr_with_changes
""",
    # CCM01: joined CTE -- mutate dateadd offset [unknown]
    "m_ccm01": """\
@@ -9,5 +9,5 @@
     select
-        dateadd(month, 1, date_month)::date as date_month,
+        dateadd(month, 2, date_month)::date as date_month,
         customer_id,
""",
}

# Verify parser classifications before running (all assertions must pass)
_EXPECTED_KINDS = {
    "m_crm01": "agg",
    "m_crm02": "agg",
    "m_crm03": "join",
    "m_crm04": "join",
    "m_crm05": "unknown",
    "m_mrr01": "unknown",
    "m_mrr02": "arithmetic",
    "m_mrr03": "unknown",
    "m_ccm01": "unknown",
}


def _validate_diffs() -> bool:
    ok = True
    for cid, expected in _EXPECTED_KINDS.items():
        got = classify_diff_kind(MRR_DIFFS[cid])
        status = "OK" if got == expected else "FAIL"
        print(f"  {cid:<10} expected={expected:<12} got={got:<12} {status}")
        if got != expected:
            ok = False
    return ok


# ---- episode cases ----
# Each case: case_id, model_rel, true_expr_id, diverged_cols, diff_id

_SPINE_DIV = frozenset(["date_month", "mrr", "is_active",
                          "first_active_month", "last_active_month",
                          "is_first_month", "is_last_month"])
_VALUE_DIV = frozenset(["mrr", "is_active",
                          "first_active_month", "last_active_month",
                          "is_first_month", "is_last_month"])

EPISODE_CASES = [
    # customer_revenue_by_month -- Group A (spine: date_month + value cols)
    {"case_id": "m_crm01", "model_rel": CRM_MODEL, "true_eid": "e_min_start",
     "div_cols": _SPINE_DIV, "diff_id": "m_crm01", "amb": True},
    {"case_id": "m_crm02", "model_rel": CRM_MODEL, "true_eid": "e_max_end",
     "div_cols": _SPINE_DIV, "diff_id": "m_crm02", "amb": True},
    {"case_id": "m_crm03", "model_rel": CRM_MODEL, "true_eid": "e_cm_join",
     "div_cols": _SPINE_DIV, "diff_id": "m_crm03", "amb": True},
    # customer_revenue_by_month -- Group B (value cols only, no date_month)
    {"case_id": "m_crm04", "model_rel": CRM_MODEL, "true_eid": "e_sub_join",
     "div_cols": _VALUE_DIV, "diff_id": "m_crm04", "amb": True},
    {"case_id": "m_crm05", "model_rel": CRM_MODEL, "true_eid": "e_coalesce_mrr",
     "div_cols": _VALUE_DIV, "diff_id": "m_crm05", "amb": True},
    # mrr.sql -- mostly unambiguous by exact_match
    {"case_id": "m_mrr01", "model_rel": MRR_MODEL, "true_eid": "e_lag_mrr",
     "div_cols": frozenset(["previous_month_mrr", "mrr_change",
                             "change_category", "renewal_amount"]),
     "diff_id": "m_mrr01", "amb": False},
    {"case_id": "m_mrr02", "model_rel": MRR_MODEL, "true_eid": "e_mrr_change",
     "div_cols": frozenset(["mrr_change", "change_category"]),
     "diff_id": "m_mrr02", "amb": False},
    {"case_id": "m_mrr03", "model_rel": MRR_MODEL, "true_eid": "e_renewal",
     "div_cols": frozenset(["renewal_amount"]),
     "diff_id": "m_mrr03", "amb": False},
    # customer_churn_month.sql -- unambiguous
    {"case_id": "m_ccm01", "model_rel": CCM_MODEL, "true_eid": "e_ccm_date",
     "div_cols": frozenset(["date_month"]),
     "diff_id": "m_ccm01", "amb": False},
]

N_CASES     = len(EPISODE_CASES)
CHECKPOINTS = [N_CASES, N_CASES * 2, N_CASES * 3, N_CASES * N_ROUNDS]


# ---- candidate filtering ----

def _get_cands(model_rel: str, diverged_cols) -> List[dict]:
    """Return candidates with any overlap with diverged_cols, indexed."""
    div_set = frozenset(diverged_cols)
    base    = EXPRESSION_CANDIDATES.get(model_rel, [])
    pool    = [c for c in base if len(c["feeds_cols"] & div_set) > 0]
    for i, c in enumerate(pool):
        c = dict(c); c["_idx"] = i
        pool[i] = c
    return pool


# ---- static ranker ----

def _rank_static(cands: List[dict], diverged_cols) -> List[int]:
    div_set = frozenset(diverged_cols)
    def key(c):
        feeds    = c["feeds_cols"]
        exact    = int(feeds == div_set)
        superset = int(div_set <= feeds)
        overlap  = int(len(feeds & div_set) > 0)
        return (-exact, -superset, -overlap, c["_idx"])
    return sorted(range(len(cands)), key=lambda i: key(cands[i]))


# ---- frequency ranker ----

def _rank_frequency(cands: List[dict], freq_ctx: Dict,
                    diverged_cols, model_rel: str,
                    static_order: List[int]) -> List[int]:
    div_set  = frozenset(diverged_cols)
    ctx_key  = (model_rel, div_set)
    ctx_hist = freq_ctx.get(ctx_key, {})

    def hist(c):
        nc, ns = ctx_hist.get(c["expr_id"], (0, 0))
        return nc / ns if ns > 0 else 0.5

    def key(i):
        return (-hist(cands[i]), static_order.index(i))

    return sorted(range(len(cands)), key=key)


# ---- feature extraction ----

def _candidate_features(cand: dict, diverged_cols, row_count_changed: bool,
                         model_rel: str, freq_ctx: Dict = None) -> List[float]:
    """10-feature vector (Phase 2a base): 9 structural + hist_freq."""
    div_set   = frozenset(diverged_cols)
    feeds     = cand["feeds_cols"]
    n_div     = len(div_set)
    n_total   = _MODEL_N_COLS.get(model_rel, max(n_div, 1))
    all_cands = EXPRESSION_CANDIDATES.get(model_rel, [cand])
    max_feeds = max(len(c["feeds_cols"]) for c in all_cands)

    exact    = float(feeds == div_set)
    superset = float(div_set <= feeds)
    overlap  = float(len(feeds & div_set) > 0)
    is_join  = float(cand["is_join"])
    is_agg   = float(cand["is_agg"])
    feeds_norm = len(feeds) / max(max_feeds, 1)
    n_div_norm = n_div / max(n_total, 1)
    row_ct   = float(row_count_changed)
    single   = float(n_div == 1)

    if freq_ctx is not None:
        ctx_key = (model_rel, div_set)
        nc, ns  = freq_ctx.get(ctx_key, {}).get(cand["expr_id"], (0, 0))
        hist    = nc / ns if ns > 0 else 0.5
    else:
        hist = 0.5

    return [exact, superset, overlap, is_join, is_agg,
            feeds_norm, n_div_norm, row_ct, single, hist]


def _features_2b(cand: dict, diverged_cols, row_count_changed: bool,
                  model_rel: str, diff_kind: str,
                  freq_ctx: Dict = None) -> List[float]:
    """11-feature vector (Phase 2b): base + diff_kind_match."""
    base = _candidate_features(cand, diverged_cols, row_count_changed,
                                model_rel, freq_ctx)
    diff_kind_match = float(
        (diff_kind == "agg"  and cand["is_agg"])
        or (diff_kind == "join" and cand["is_join"])
    )
    return base + [diff_kind_match]


# ---- learner ----

def _fit(X: List[List[float]], y: List[int]):
    if len(X) < 4 or sum(y) < 2:
        return None
    try:
        from sklearn.linear_model import LogisticRegression
        clf = LogisticRegression(C=1.0, max_iter=500, solver="lbfgs")
        clf.fit(X, y)
        return clf
    except Exception:
        return None


def _rank_learned(cands: List[dict], diverged_cols, row_count_changed: bool,
                   model_rel: str, clf, static_order: List[int],
                   freq_ctx: Dict = None,
                   diff_kind: str = None,
                   use_2b: bool = False) -> List[int]:
    if clf is None:
        return static_order[:]

    if use_2b and diff_kind is not None:
        feats = [_features_2b(c, diverged_cols, row_count_changed,
                              model_rel, diff_kind, freq_ctx) for c in cands]
    else:
        feats = [_candidate_features(c, diverged_cols, row_count_changed,
                                     model_rel, freq_ctx) for c in cands]

    try:
        scores = clf.predict_proba(feats)[:, 1]
    except Exception:
        return static_order[:]

    ranked = sorted(range(len(cands)), key=lambda i: (-scores[i], static_order.index(i)))
    return ranked


# ---- MRR helpers ----

def _rr(rank_order: List[int], true_idx: int) -> float:
    try:
        return 1.0 / (rank_order.index(true_idx) + 1)
    except ValueError:
        return 0.0


# ---- main simulation ----

def run_simulation():
    # Validate diff hunks before starting
    print("\nValidating diff hunk classifications for mrr-playbook:")
    if not _validate_diffs():
        raise RuntimeError("Diff validation failed — fix hunks before running.")
    print()

    # Build episode list: N_ROUNDS rounds, each round shuffled independently
    all_episodes = []
    for rnd, seed in enumerate(ROUND_SEEDS):
        rng     = random.Random(seed)
        indices = list(range(N_CASES))
        rng.shuffle(indices)
        for case_idx in indices:
            case = EPISODE_CASES[case_idx]
            all_episodes.append((rnd + 1, case))

    total_eps = len(all_episodes)
    print(f"Detectable mutations: {N_CASES}")
    print(f"Total episodes: {total_eps}")

    # State
    freq_ctx: Dict[Tuple, Dict[str, Tuple[int, int]]] = {}
    X_2a: List[List[float]] = []
    y_2a: List[int]          = []
    X_2b: List[List[float]]  = []
    y_2b: List[int]          = []

    clf_2a = None
    clf_2b = None

    # Accumulators
    rr_static  = []
    rr_freq    = []
    rrs_2a     = []
    rrs_2b     = []
    ep_detail  = []

    print(f"\n{'='*72}")
    print(f"Phase 2b TRANSFER -- mrr-playbook (dbt-labs/mrr-playbook)")
    print(f"Registered prediction: borderline GREEN/YELLOW")
    print(f"Ambiguity: CASCADE (agg feeds join condition); MIXED diff_kind confirmed")
    print(f"{'='*72}")

    for ep_idx, (rnd, case) in enumerate(all_episodes):
        case_id   = case["case_id"]
        model_rel = case["model_rel"]
        true_eid  = case["true_eid"]
        div_cols  = case["div_cols"]
        diff_id   = case["diff_id"]
        hunk      = MRR_DIFFS[diff_id]

        # Parse diff_kind from the real hunk (no hardcoding)
        diff_kind = classify_diff_kind(hunk)

        row_ct    = False   # mrr-playbook mutations don't affect row count
        div_set   = frozenset(div_cols)

        # Get candidate pool and static ranking
        cands       = _get_cands(model_rel, div_cols)
        static_order = _rank_static(cands, div_cols)
        true_idx    = next((i for i, c in enumerate(cands)
                            if c["expr_id"] == true_eid), 0)

        # Rank with each method
        freq_order = _rank_frequency(cands, freq_ctx, div_cols,
                                     model_rel, static_order)
        learned_2a = _rank_learned(cands, div_cols, row_ct, model_rel,
                                    clf_2a, static_order, freq_ctx,
                                    diff_kind=None, use_2b=False)
        learned_2b = _rank_learned(cands, div_cols, row_ct, model_rel,
                                    clf_2b, static_order, freq_ctx,
                                    diff_kind=diff_kind, use_2b=True)

        # Collect RRs
        rr_s_ep  = _rr(static_order, true_idx)
        rr_f_ep  = _rr(freq_order,   true_idx)
        rr_2a_ep = _rr(learned_2a,   true_idx)
        rr_2b_ep = _rr(learned_2b,   true_idx)

        rr_static.append(rr_s_ep)
        rr_freq.append(rr_f_ep)
        rrs_2a.append(rr_2a_ep)
        rrs_2b.append(rr_2b_ep)

        ep_detail.append({
            "ep": ep_idx + 1, "rnd": rnd,
            "case_id": case_id,
            "diff_kind": diff_kind,
            "amb": case["amb"],
            "n_cands": len(cands),
            "r_s": static_order.index(true_idx) + 1,
            "r_f": freq_order.index(true_idx) + 1,
            "r_2a": learned_2a.index(true_idx) + 1,
            "r_2b": learned_2b.index(true_idx) + 1,
            "rr_s": round(rr_s_ep, 3), "rr_f": round(rr_f_ep, 3),
            "rr_2a": round(rr_2a_ep, 3), "rr_2b": round(rr_2b_ep, 3),
        })

        # Update frequency
        ctx_key = (model_rel, div_set)
        if ctx_key not in freq_ctx:
            freq_ctx[ctx_key] = {}
        for c in cands:
            nc, ns = freq_ctx[ctx_key].get(c["expr_id"], (0, 0))
            freq_ctx[ctx_key][c["expr_id"]] = (
                nc + int(c["expr_id"] == true_eid), ns + 1
            )

        # Collect training features
        for i, c in enumerate(cands):
            is_correct = int(c["expr_id"] == true_eid)
            X_2a.append(_candidate_features(c, div_cols, row_ct,
                                             model_rel, freq_ctx))
            y_2a.append(is_correct)
            X_2b.append(_features_2b(c, div_cols, row_ct, model_rel,
                                      diff_kind, freq_ctx))
            y_2b.append(is_correct)

        # Refit classifiers
        clf_2a = _fit(X_2a, y_2a)
        clf_2b = _fit(X_2b, y_2b)

        # Checkpoints
        ep_num = ep_idx + 1
        if ep_num in CHECKPOINTS:
            mrr_s  = float(np.mean(rr_static[:ep_num]))
            mrr_f  = float(np.mean(rr_freq[:ep_num]))
            mrr_2a = float(np.mean(rrs_2a[:ep_num]))
            mrr_2b = float(np.mean(rrs_2b[:ep_num]))
            d_vs_s  = mrr_2b - mrr_s
            d_vs_f  = mrr_2b - mrr_f
            d_vs_2a = mrr_2b - mrr_2a
            if d_vs_s > DELTA and d_vs_f > DELTA:
                tag = "GREEN"
            elif d_vs_s > DELTA:
                tag = "YELLOW"
            else:
                tag = "RED"

            print(f"\n--- Checkpoint: episode {ep_num} ---")
            print(f"  {'Method':<14} {'MRR':>7}   {'MRR_uniq':>9}   {'MRR_amb':>8}")
            print(f"  {'-'*44}")
            for method, rrs in [("static", rr_static),
                                 ("frequency", rr_freq),
                                 ("learned_2a", rrs_2a),
                                 ("learned_2b", rrs_2b)]:
                uniq = [x for x, d in zip(rrs[:ep_num], ep_detail[:ep_num]) if not d["amb"]]
                amb  = [x for x, d in zip(rrs[:ep_num], ep_detail[:ep_num]) if d["amb"]]
                m_all  = float(np.mean(rrs[:ep_num]))
                m_uniq = float(np.mean(uniq)) if uniq else float("nan")
                m_amb  = float(np.mean(amb))  if amb  else float("nan")
                print(f"  {method:<14} {m_all:>7.3f}   {m_uniq:>9.3f}   {m_amb:>8.3f}")
            print(f"  2b: d_vs_static={d_vs_s:+.3f}  d_vs_freq={d_vs_f:+.3f}"
                  f"  d_vs_2a={d_vs_2a:+.3f}  -> {tag}")

    # Final verdict
    final_ep   = total_eps
    mrr_s      = float(np.mean(rr_static))
    mrr_f      = float(np.mean(rr_freq))
    mrr_2a_val = float(np.mean(rrs_2a))
    mrr_2b_val = float(np.mean(rrs_2b))
    d_vs_s     = mrr_2b_val - mrr_s
    d_vs_f     = mrr_2b_val - mrr_f
    d_vs_2a    = mrr_2b_val - mrr_2a_val

    if d_vs_s > DELTA and d_vs_f > DELTA:
        verdict = "GREEN"
        interp  = "Diff-context representation transfers to cascade-ambiguity target"
    elif d_vs_s > DELTA:
        verdict = "YELLOW"
        interp  = "Experience helps as caching but freq captures most of the gain"
    else:
        verdict = "RED"
        interp  = ("Mechanism does not transfer, or cascade ambiguity requires "
                   "finer representation than diff_kind (lineage-depth / clause location)")

    print(f"\n{'='*72}")
    print(f"PHASE 2B TRANSFER VERDICT: {verdict}")
    print(f"  Project              : dbt-labs/mrr-playbook (CASCADE ambiguity)")
    print(f"  MRR static           : {mrr_s:.3f}")
    print(f"  MRR frequency        : {mrr_f:.3f}")
    print(f"  MRR learned_2a       : {mrr_2a_val:.3f}")
    print(f"  MRR learned_2b       : {mrr_2b_val:.3f}")
    print(f"  delta_2b_vs_static   : {d_vs_s:+.3f}  (threshold: >0.05 for GREEN)")
    print(f"  delta_2b_vs_freq     : {d_vs_f:+.3f}  (threshold: >0.05 for GREEN)")
    print(f"  delta_2b_vs_2a       : {d_vs_2a:+.3f}")
    print(f"  Interpretation       : {interp}")
    print(f"{'='*72}")

    # Cascade-specific analysis
    print(f"\nCascade ambiguity analysis (Group A: e_min_start/e_max_end/e_cm_join):")
    grp_a = [d for d in ep_detail if d["case_id"] in ("m_crm01", "m_crm02", "m_crm03")]
    for case_id in ("m_crm01", "m_crm02", "m_crm03"):
        eps  = [d for d in grp_a if d["case_id"] == case_id]
        true_eps = EPISODE_CASES[next(i for i, e in enumerate(EPISODE_CASES)
                                      if e["case_id"] == case_id)]
        dk = eps[0]["diff_kind"] if eps else "?"
        avg_s  = np.mean([e["rr_s"]  for e in eps])
        avg_f  = np.mean([e["rr_f"]  for e in eps])
        avg_2a = np.mean([e["rr_2a"] for e in eps])
        avg_2b = np.mean([e["rr_2b"] for e in eps])
        print(f"  {case_id} (true={true_eps['true_eid']}, diff={dk}): "
              f"static={avg_s:.3f} freq={avg_f:.3f} 2a={avg_2a:.3f} 2b={avg_2b:.3f}")

    print(f"\nValue-join ambiguity (Group B: e_sub_join/e_coalesce_mrr):")
    for case_id in ("m_crm04", "m_crm05"):
        eps  = [d for d in ep_detail if d["case_id"] == case_id]
        true_eps = EPISODE_CASES[next(i for i, e in enumerate(EPISODE_CASES)
                                      if e["case_id"] == case_id)]
        dk = eps[0]["diff_kind"] if eps else "?"
        avg_s  = np.mean([e["rr_s"]  for e in eps])
        avg_f  = np.mean([e["rr_f"]  for e in eps])
        avg_2a = np.mean([e["rr_2a"] for e in eps])
        avg_2b = np.mean([e["rr_2b"] for e in eps])
        print(f"  {case_id} (true={true_eps['true_eid']}, diff={dk}): "
              f"static={avg_s:.3f} freq={avg_f:.3f} 2a={avg_2a:.3f} 2b={avg_2b:.3f}")

    # Feature weights
    def _print_weights(clf, feature_names, label):
        if clf is None:
            print(f"  {label}: no model (insufficient data)")
            return
        w = clf.coef_[0]
        pairs = sorted(zip(feature_names, w), key=lambda x: -abs(x[1]))
        print(f"  {label}:")
        for name, wt in pairs:
            print(f"    {name:<22} : {wt:+.3f}")

    feat_names_2a = ["exact_match", "superset_match", "any_overlap",
                     "is_join", "is_agg", "feeds_norm", "n_div_norm",
                     "row_count_changed", "single_col", "hist_freq"]
    feat_names_2b = feat_names_2a + ["diff_kind_match"]

    print(f"\nFeature weights:")
    _print_weights(clf_2a, feat_names_2a, "learned_2a")
    _print_weights(clf_2b, feat_names_2b, "learned_2b")

    # Per-episode detail
    print(f"\nPer-episode detail:")
    hdr = f"{'ep':>4} {'rnd':>4} {'case_id':<10} {'dk':<10} {'amb':<4} {'nc':>3} {'r_s':>4} {'r_f':>4} {'r_2a':>5} {'r_2b':>5} {'rr_s':>6} {'rr_f':>6} {'rr_2a':>7} {'rr_2b':>7}"
    print(f"  {hdr}")
    print(f"  {'-'*80}")
    for d in ep_detail:
        amb_tag = "Y" if d["amb"] else "N"
        print(f"  {d['ep']:>4} {d['rnd']:>4}  {d['case_id']:<10} "
              f"{d['diff_kind']:<10} {amb_tag:<4} {d['n_cands']:>3} "
              f"{d['r_s']:>4} {d['r_f']:>4} {d['r_2a']:>5} {d['r_2b']:>5} "
              f"{d['rr_s']:>6.3f} {d['rr_f']:>6.3f} "
              f"{d['rr_2a']:>7.3f} {d['rr_2b']:>7.3f}")

    # Save results
    result = {
        "project": "dbt-labs/mrr-playbook",
        "ambiguity_structure": "CASCADE (agg feeds join condition bounds)",
        "n_cases": N_CASES, "n_rounds": N_ROUNDS, "total_episodes": total_eps,
        "mrr_static": mrr_s, "mrr_freq": mrr_f,
        "mrr_2a": mrr_2a_val, "mrr_2b": mrr_2b_val,
        "delta_vs_static": d_vs_s, "delta_vs_freq": d_vs_f, "delta_vs_2a": d_vs_2a,
        "verdict": verdict, "interpretation": interp,
        "feature_weights_2a": (
            dict(zip(feat_names_2a, clf_2a.coef_[0].tolist())) if clf_2a else None),
        "feature_weights_2b": (
            dict(zip(feat_names_2b, clf_2b.coef_[0].tolist())) if clf_2b else None),
        "episodes": ep_detail,
    }
    OUT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"\nResults saved: {OUT}")
    return result


if __name__ == "__main__":
    run_simulation()
