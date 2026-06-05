"""
dbt_phase4_vstarlite.py -- V-STaR-style pairwise localizer for dbt expressions.

Three things over Phase 3 (pointwise logistic regression):

1. PAIRWISE SIGNAL (Bradley-Terry / RankNet).
   Training signal = (features_true - features_wrong) difference vectors → label=1.
   Inference: rank by w·features_i, where w is the pairwise LR weight.
   The pairwise form directly encodes "what features distinguish true from wrong in this
   episode" — factoring out shared features the pointwise form cannot isolate.

2. CROSS-PROJECT ZERO-SHOT TRANSFER.
   Train on mrr-playbook episodes only → evaluate on stripe (zero-shot, no stripe training).
   Train on stripe episodes only → evaluate on mrr-playbook (reverse).
   If CE oracle produces a universalizing signal, cross-project pairwise should approach
   per-project pointwise (Phase 3) without any within-project training.

3. JOINT TRAINING.
   Train on both projects → evaluate on both.
   Expected: better than per-project training on hard cases (sub-dk subset), because
   hard cases from mrr-playbook and stripe are structurally similar (both agg+alias
   disambiguation) even across different SQL patterns.

Thread A connection:
   Construction-embedded oracle → universalizing signal.
   If cross-project pairwise >= (or approaches) Phase 3 per-project, the CE oracle IS
   the generalizing signal — not project-specific features.

Thread B connection (V-STaR interpretation):
   Phase 4 is the "verifier" in V-STaR: trained on FAILURES of the static ranker
   across both projects, it learns which feature differences predict correct ranking.
   The "reasoner" is the pairwise ranker itself; the oracle is the construction-embedded
   mutation ground truth.
"""

import json
import re
import random
import pathlib
from typing import Dict, List, Tuple

import numpy as np
from diff_parser import classify_diff_kind, _split_hunk

HERE = pathlib.Path(__file__).resolve().parent
OUT  = HERE / "dbt_phase4_vstarlite_results.json"

DELTA    = 0.05
N_ROUNDS = 4

# =========================================================
# ---- Candidate definitions (Phase 3 data, both projects)
# =========================================================

CRM_MODEL   = "models/customer_revenue_by_month.sql"
MRR_MODEL   = "models/mrr.sql"
CCM_MODEL   = "models/customer_churn_month.sql"
STRIPE_MODEL = "models/stripe__invoice_details.sql"

_MODEL_N_COLS = {
    CRM_MODEL:    8,
    MRR_MODEL:   14,
    CCM_MODEL:    8,
    STRIPE_MODEL: 35,
}

# mrr-playbook candidate sets
_CRM_SPINE_COLS = frozenset(["date_month","mrr","is_active","first_active_month",
                              "last_active_month","is_first_month","is_last_month"])
_CRM_VALUE_COLS = frozenset(["mrr","is_active","first_active_month","last_active_month",
                              "is_first_month","is_last_month"])

MRR_CANDIDATES = {
    CRM_MODEL: [
        {"expr_id":"e_min_start","feeds_cols":_CRM_SPINE_COLS,
         "is_agg":True,"is_join":False,"line":18,"alias":"date_month_start","joined_table":""},
        {"expr_id":"e_max_end","feeds_cols":_CRM_SPINE_COLS,
         "is_agg":True,"is_join":False,"line":19,"alias":"date_month_end","joined_table":""},
        {"expr_id":"e_cm_join","feeds_cols":_CRM_SPINE_COLS,
         "is_agg":False,"is_join":True,"line":37,"alias":"","joined_table":"months"},
        {"expr_id":"e_sub_join","feeds_cols":_CRM_VALUE_COLS,
         "is_agg":False,"is_join":True,"line":56,"alias":"","joined_table":"subscription_periods"},
        {"expr_id":"e_coalesce_mrr","feeds_cols":_CRM_VALUE_COLS,
         "is_agg":False,"is_join":False,"line":52,"alias":"mrr","joined_table":""},
    ],
    MRR_MODEL: [
        {"expr_id":"e_lag_mrr","feeds_cols":frozenset(["previous_month_mrr","mrr_change",
          "change_category","renewal_amount"]),
         "is_agg":False,"is_join":False,"line":23,"alias":"previous_month_mrr","joined_table":""},
        {"expr_id":"e_mrr_change","feeds_cols":frozenset(["mrr_change","change_category"]),
         "is_agg":False,"is_join":False,"line":27,"alias":"mrr_change","joined_table":""},
        {"expr_id":"e_renewal","feeds_cols":frozenset(["renewal_amount"]),
         "is_agg":False,"is_join":False,"line":53,"alias":"renewal_amount","joined_table":""},
    ],
    CCM_MODEL: [
        {"expr_id":"e_ccm_date","feeds_cols":frozenset(["date_month"]),
         "is_agg":False,"is_join":False,"line":11,"alias":"date_month","joined_table":""},
    ],
}

# stripe candidate set
_GROUP_A_COLS = frozenset(["number_of_line_items","total_quantity"])
_GROUP_B_COLS = frozenset(["charge_amount","charge_status","charge_created_at","charge_is_refunded"])
_GROUP_C_COLS = frozenset(["subscription_billing","subscription_start_date","subscription_ended_at"])
_GROUP_D_COLS = frozenset(["customer_id","customer_description","customer_account_balance",
                            "customer_currency","customer_is_delinquent","customer_email"])

STRIPE_CANDIDATES = {
    STRIPE_MODEL: [
        {"expr_id":"e_count_lines","feeds_cols":_GROUP_A_COLS,
         "is_agg":True,"is_join":False,"line":18,"alias":"number_of_line_items","joined_table":""},
        {"expr_id":"e_sum_qty","feeds_cols":_GROUP_A_COLS,
         "is_agg":True,"is_join":False,"line":19,"alias":"total_quantity","joined_table":""},
        {"expr_id":"e_join_ili","feeds_cols":_GROUP_A_COLS,
         "is_agg":False,"is_join":True,"line":91,"alias":"","joined_table":"invoice_line_item"},
        {"expr_id":"e_join_charge","feeds_cols":_GROUP_B_COLS,
         "is_agg":False,"is_join":True,"line":95,"alias":"","joined_table":"charge"},
        {"expr_id":"e_join_sub","feeds_cols":_GROUP_C_COLS,
         "is_agg":False,"is_join":True,"line":101,"alias":"","joined_table":"subscription"},
        {"expr_id":"e_join_cust","feeds_cols":_GROUP_D_COLS,
         "is_agg":False,"is_join":True,"line":107,"alias":"","joined_table":"customer"},
    ],
}

# merged
ALL_CANDIDATES = {**MRR_CANDIDATES, **STRIPE_CANDIDATES}

# =========================================================
# ---- Diff hunks (same as Phase 3 scripts)
# =========================================================

MRR_DIFFS = {
    "m_crm01": "@@ -16,5 +16,5 @@\n     select\n         customer_id,\n-        date_trunc('month', min(start_date)) as date_month_start,\n+        date_trunc('month', min(start_date + 1)) as date_month_start,\n         date_trunc('month', max(end_date)) as date_month_end\n",
    "m_crm02": "@@ -17,5 +17,5 @@\n         customer_id,\n         date_trunc('month', min(start_date)) as date_month_start,\n-        date_trunc('month', max(end_date)) as date_month_end\n+        date_trunc('month', max(end_date + 1)) as date_month_end\n\n     from subscription_periods\n",
    "m_crm03": "@@ -37,6 +37,6 @@\n     inner join months\n         -- all months after start date\n-        on  months.date_month >= customers.date_month_start\n+        on  months.date_month > customers.date_month_start\n         -- and before end date\n         and months.date_month < customers.date_month_end\n",
    "m_crm04": "@@ -56,6 +56,6 @@\n     left join subscription_periods\n-        on customer_months.customer_id = subscription_periods.customer_id\n+        on customer_months.customer_id != subscription_periods.customer_id\n         -- month is after a subscription start date\n         and customer_months.date_month >= subscription_periods.start_date\n",
    "m_crm05": "@@ -49,5 +49,5 @@\n         customer_months.date_month,\n         customer_months.customer_id,\n-        coalesce(subscription_periods.monthly_amount, 0) as mrr\n+        coalesce(subscription_periods.monthly_amount, 1) as mrr\n\n     from customer_months\n",
    "m_mrr01": "@@ -21,5 +21,5 @@\n         coalesce(\n-            lag(mrr) over (partition by customer_id order by date_month),\n+            lag(mrr, 2) over (partition by customer_id order by date_month),\n             0\n         ) as previous_month_mrr,\n",
    "m_mrr02": "@@ -25,5 +25,5 @@\n         ) as previous_month_mrr,\n\n-        mrr - previous_month_mrr as mrr_change\n+        mrr - previous_month_mrr - 1 as mrr_change\n\n     from unioned\n",
    "m_mrr03": "@@ -51,5 +51,5 @@\n\n-        least(mrr, previous_month_mrr) as renewal_amount\n+        greatest(mrr, previous_month_mrr) as renewal_amount\n\n     from mrr_with_changes\n",
    "m_ccm01": "@@ -9,5 +9,5 @@\n     select\n-        dateadd(month, 1, date_month)::date as date_month,\n+        dateadd(month, 2, date_month)::date as date_month,\n         customer_id,\n",
}

STRIPE_DIFFS = {
    "s_inv01": "@@ -16,6 +16,6 @@\n     select\n         invoice_id,\n         source_relation,\n-        coalesce(count(distinct unique_invoice_line_item_id),0) as number_of_line_items,\n+        coalesce(count(unique_invoice_line_item_id),0) as number_of_line_items,\n         coalesce(sum(quantity),0) as total_quantity\n",
    "s_inv02": "@@ -17,6 +17,6 @@\n         invoice_id,\n         source_relation,\n         coalesce(count(distinct unique_invoice_line_item_id),0) as number_of_line_items,\n-        coalesce(sum(quantity),0) as total_quantity\n+        coalesce(sum(quantity * 2),0) as total_quantity\n\n",
    "s_inv03": "@@ -91,5 +91,5 @@\n left join invoice_line_item\n-    on invoice.invoice_id = invoice_line_item.invoice_id\n+    on invoice.invoice_id != invoice_line_item.invoice_id\n     and invoice.source_relation = invoice_line_item.source_relation\n",
    "s_inv04": "@@ -96,5 +96,5 @@\n left join charge\n-    on invoice.charge_id = charge.charge_id\n+    on invoice.charge_id != charge.charge_id\n     and invoice.invoice_id = charge.invoice_id\n",
    "s_inv05": "@@ -101,5 +101,5 @@\n left join subscription\n-    on invoice.subscription_id = subscription.subscription_id\n+    on invoice.subscription_id != subscription.subscription_id\n     and invoice.source_relation = subscription.source_relation\n",
    "s_inv06": "@@ -107,5 +107,5 @@\n left join customer\n-    on invoice.customer_id = customer.customer_id\n+    on invoice.customer_id != customer.customer_id\n     and invoice.source_relation = customer.source_relation\n",
}

ALL_DIFFS = {**MRR_DIFFS, **STRIPE_DIFFS}

# =========================================================
# ---- Episode cases (from Phase 3 scripts)
# =========================================================

_SPINE_DIV = frozenset(["date_month","mrr","is_active","first_active_month",
                          "last_active_month","is_first_month","is_last_month"])
_VALUE_DIV  = frozenset(["mrr","is_active","first_active_month","last_active_month",
                          "is_first_month","is_last_month"])

MRR_EPISODES = [
    {"case_id":"m_crm01","model_rel":CRM_MODEL,"true_eid":"e_min_start",
     "div_cols":_SPINE_DIV,"diff_id":"m_crm01","sub_dk":True,"project":"mrr"},
    {"case_id":"m_crm02","model_rel":CRM_MODEL,"true_eid":"e_max_end",
     "div_cols":_SPINE_DIV,"diff_id":"m_crm02","sub_dk":True,"project":"mrr"},
    {"case_id":"m_crm03","model_rel":CRM_MODEL,"true_eid":"e_cm_join",
     "div_cols":_SPINE_DIV,"diff_id":"m_crm03","sub_dk":False,"project":"mrr"},
    {"case_id":"m_crm04","model_rel":CRM_MODEL,"true_eid":"e_sub_join",
     "div_cols":_VALUE_DIV,"diff_id":"m_crm04","sub_dk":False,"project":"mrr"},
    {"case_id":"m_crm05","model_rel":CRM_MODEL,"true_eid":"e_coalesce_mrr",
     "div_cols":_VALUE_DIV,"diff_id":"m_crm05","sub_dk":False,"project":"mrr"},
    {"case_id":"m_mrr01","model_rel":MRR_MODEL,"true_eid":"e_lag_mrr",
     "div_cols":frozenset(["previous_month_mrr","mrr_change","change_category","renewal_amount"]),
     "diff_id":"m_mrr01","sub_dk":False,"project":"mrr"},
    {"case_id":"m_mrr02","model_rel":MRR_MODEL,"true_eid":"e_mrr_change",
     "div_cols":frozenset(["mrr_change","change_category"]),
     "diff_id":"m_mrr02","sub_dk":False,"project":"mrr"},
    {"case_id":"m_mrr03","model_rel":MRR_MODEL,"true_eid":"e_renewal",
     "div_cols":frozenset(["renewal_amount"]),
     "diff_id":"m_mrr03","sub_dk":False,"project":"mrr"},
    {"case_id":"m_ccm01","model_rel":CCM_MODEL,"true_eid":"e_ccm_date",
     "div_cols":frozenset(["date_month"]),
     "diff_id":"m_ccm01","sub_dk":False,"project":"mrr"},
]

STRIPE_EPISODES = [
    {"case_id":"s_inv01","model_rel":STRIPE_MODEL,"true_eid":"e_count_lines",
     "div_cols":_GROUP_A_COLS,"diff_id":"s_inv01","sub_dk":True,"project":"stripe"},
    {"case_id":"s_inv02","model_rel":STRIPE_MODEL,"true_eid":"e_sum_qty",
     "div_cols":_GROUP_A_COLS,"diff_id":"s_inv02","sub_dk":True,"project":"stripe"},
    {"case_id":"s_inv03","model_rel":STRIPE_MODEL,"true_eid":"e_join_ili",
     "div_cols":_GROUP_A_COLS,"diff_id":"s_inv03","sub_dk":False,"project":"stripe"},
    {"case_id":"s_inv04","model_rel":STRIPE_MODEL,"true_eid":"e_join_charge",
     "div_cols":_GROUP_B_COLS,"diff_id":"s_inv04","sub_dk":False,"project":"stripe"},
    {"case_id":"s_inv05","model_rel":STRIPE_MODEL,"true_eid":"e_join_sub",
     "div_cols":_GROUP_C_COLS,"diff_id":"s_inv05","sub_dk":False,"project":"stripe"},
    {"case_id":"s_inv06","model_rel":STRIPE_MODEL,"true_eid":"e_join_cust",
     "div_cols":_GROUP_D_COLS,"diff_id":"s_inv06","sub_dk":False,"project":"stripe"},
]

# =========================================================
# ---- Feature extraction (identical to Phase 3)
# =========================================================

def _alias_in_hunk(cand: dict, hunk: str) -> float:
    changed, full = _split_hunk(hunk)
    if cand["is_join"]:
        tbl = cand.get("joined_table","")
        if not tbl: return 0.0
        return float(bool(re.search(r'\b' + re.escape(tbl) + r'\b', full, re.IGNORECASE)))
    else:
        alias = cand.get("alias","")
        if not alias: return 0.0
        return float(bool(re.search(r'\bAS\s+' + re.escape(alias) + r'\b', changed, re.IGNORECASE)))


def _features_3(cand: dict, diverged_cols, model_rel: str,
                 diff_kind: str, freq_ctx: Dict = None, hunk: str = "") -> List[float]:
    """12-feature Phase 3 vector."""
    div_set   = frozenset(diverged_cols)
    feeds     = cand["feeds_cols"]
    n_div     = len(div_set)
    n_total   = _MODEL_N_COLS.get(model_rel, max(n_div, 1))
    all_cands = ALL_CANDIDATES.get(model_rel, [cand])
    max_feeds = max(len(c["feeds_cols"]) for c in all_cands)

    exact      = float(feeds == div_set)
    superset   = float(div_set <= feeds)
    overlap    = float(len(feeds & div_set) > 0)
    is_join    = float(cand["is_join"])
    is_agg     = float(cand["is_agg"])
    feeds_norm = len(feeds) / max(max_feeds, 1)
    n_div_norm = n_div / max(n_total, 1)
    single     = float(n_div == 1)

    if freq_ctx is not None:
        ctx_key = (model_rel, div_set)
        nc, ns  = freq_ctx.get(ctx_key, {}).get(cand["expr_id"], (0, 0))
        hist    = nc / ns if ns > 0 else 0.5
    else:
        hist = 0.5

    diff_kind_match = float(
        (diff_kind == "agg"  and cand["is_agg"])
        or (diff_kind == "join" and cand["is_join"])
    )
    alias_feat = _alias_in_hunk(cand, hunk)

    return [exact, superset, overlap, is_join, is_agg,
            feeds_norm, n_div_norm, 0.0, single, hist,
            diff_kind_match, alias_feat]


FEAT_NAMES = ["exact_match","superset_match","any_overlap","is_join","is_agg",
              "feeds_norm","n_div_norm","row_count_changed","single_col","hist_freq",
              "diff_kind_match","alias_in_hunk"]


def _get_cands(model_rel: str, diverged_cols) -> List[dict]:
    div_set = frozenset(diverged_cols)
    base    = ALL_CANDIDATES.get(model_rel, [])
    pool    = [c for c in base if len(c["feeds_cols"] & div_set) > 0]
    for i, c in enumerate(pool):
        c = dict(c); c["_idx"] = i
        pool[i] = c
    return pool


def _rank_static(cands: List[dict], diverged_cols) -> List[int]:
    div_set = frozenset(diverged_cols)
    def key(c):
        feeds = c["feeds_cols"]
        return (-int(feeds==div_set), -int(div_set<=feeds), -int(len(feeds&div_set)>0), c["_idx"])
    return sorted(range(len(cands)), key=lambda i: key(cands[i]))


# =========================================================
# ---- Pointwise learner (Phase 3 baseline)
# =========================================================

def _fit_pointwise(X: List[List[float]], y: List[int]):
    if len(X) < 4 or sum(y) < 2: return None
    try:
        from sklearn.linear_model import LogisticRegression
        clf = LogisticRegression(C=1.0, max_iter=500, solver="lbfgs")
        clf.fit(X, y)
        return clf
    except Exception: return None


def _rank_pointwise(cands, diverged_cols, model_rel, clf, static_order,
                    freq_ctx, diff_kind, hunk) -> List[int]:
    if clf is None: return static_order[:]
    feats = [_features_3(c, diverged_cols, model_rel, diff_kind, freq_ctx, hunk)
             for c in cands]
    try:
        scores = clf.predict_proba(feats)[:, 1]
    except Exception: return static_order[:]
    return sorted(range(len(cands)), key=lambda i: (-scores[i], static_order.index(i)))


# =========================================================
# ---- Pairwise learner (V-STaR-style)
# =========================================================

def _fit_pairwise(pairs_X: List[List[float]], pairs_y: List[int]):
    """
    Bradley-Terry pairwise LR.
    Training: diff_vector = features_true - features_wrong → label=1
    Inference: score_i = w · features_i  (equivalent to ranking by margin)
    """
    if len(pairs_X) < 4 or sum(pairs_y) < 2: return None
    try:
        from sklearn.linear_model import LogisticRegression
        clf = LogisticRegression(C=1.0, max_iter=500, solver="lbfgs")
        clf.fit(pairs_X, pairs_y)
        return clf
    except Exception: return None


def _rank_pairwise(cands, diverged_cols, model_rel, clf, static_order,
                   freq_ctx, diff_kind, hunk) -> List[int]:
    """Rank by w·features_i, ties broken by static order."""
    if clf is None: return static_order[:]
    feats  = [_features_3(c, diverged_cols, model_rel, diff_kind, freq_ctx, hunk)
              for c in cands]
    w      = clf.coef_[0]
    scores = [float(np.dot(w, f)) for f in feats]
    return sorted(range(len(cands)), key=lambda i: (-scores[i], static_order.index(i)))


# =========================================================
# ---- Episode runner (collects pointwise + pairwise data)
# =========================================================

def _run_episodes(cases: List[dict], seeds: List[int],
                  clf_pw=None, clf_pr=None,
                  freq_ctx: Dict = None,
                  collect: bool = True):
    """
    Run episodes for `cases` over `len(seeds)` rounds.
    Returns:
      rr_static, rr_pw, rr_pr  (per-episode RR lists)
      X_pw, y_pw                (pointwise training data)
      pairs_X, pairs_y          (pairwise training data)
      ep_detail                 (list of per-episode dicts)
    """
    if freq_ctx is None: freq_ctx = {}

    all_eps = []
    for rnd, seed in enumerate(seeds):
        rng = random.Random(seed)
        idx = list(range(len(cases))); rng.shuffle(idx)
        for ci in idx: all_eps.append((rnd + 1, cases[ci]))

    rr_static, rr_pw, rr_pr = [], [], []
    X_pw, y_pw  = [], []
    pairs_X, pairs_y = [], []
    ep_detail   = []

    for ep_idx, (rnd, case) in enumerate(all_eps):
        model_rel = case["model_rel"]
        true_eid  = case["true_eid"]
        div_cols  = case["div_cols"]
        hunk      = ALL_DIFFS[case["diff_id"]]
        diff_kind = classify_diff_kind(hunk)
        div_set   = frozenset(div_cols)
        cands     = _get_cands(model_rel, div_cols)
        s_order   = _rank_static(cands, div_cols)
        true_idx  = next((i for i, c in enumerate(cands) if c["expr_id"] == true_eid), 0)

        pw_order = _rank_pointwise(cands, div_cols, model_rel, clf_pw, s_order,
                                   freq_ctx, diff_kind, hunk)
        pr_order = _rank_pairwise(cands, div_cols, model_rel, clf_pr, s_order,
                                  freq_ctx, diff_kind, hunk)

        def rr(order): return 1.0 / (order.index(true_idx) + 1)
        rr_s  = rr(s_order)
        rr_pw_ = rr(pw_order)
        rr_pr_ = rr(pr_order)
        rr_static.append(rr_s)
        rr_pw.append(rr_pw_)
        rr_pr.append(rr_pr_)

        ep_detail.append({
            "case_id": case["case_id"],
            "project": case.get("project","?"),
            "sub_dk":  case["sub_dk"],
            "rnd": rnd, "diff_kind": diff_kind, "n_cands": len(cands),
            "r_s":  s_order.index(true_idx)+1,
            "r_pw": pw_order.index(true_idx)+1,
            "r_pr": pr_order.index(true_idx)+1,
            "rr_s":  round(rr_s,3), "rr_pw": round(rr_pw_,3), "rr_pr": round(rr_pr_,3),
        })

        # Update frequency
        ctx_key = (model_rel, div_set)
        if ctx_key not in freq_ctx: freq_ctx[ctx_key] = {}
        for c in cands:
            nc, ns = freq_ctx[ctx_key].get(c["expr_id"], (0, 0))
            freq_ctx[ctx_key][c["expr_id"]] = (nc + int(c["expr_id"]==true_eid), ns+1)

        if collect:
            true_feats = _features_3(cands[true_idx], div_cols, model_rel,
                                     diff_kind, freq_ctx, hunk)
            for i, c in enumerate(cands):
                feats = _features_3(c, div_cols, model_rel, diff_kind, freq_ctx, hunk)
                label = int(c["expr_id"] == true_eid)
                X_pw.append(feats)
                y_pw.append(label)
                # Pairwise: (true - this) if this is wrong; (this - true) if this is wrong flipped
                if i != true_idx:
                    diff_pos = [a - b for a, b in zip(true_feats, feats)]
                    diff_neg = [a - b for a, b in zip(feats, true_feats)]
                    pairs_X.extend([diff_pos, diff_neg])
                    pairs_y.extend([1, 0])

    return rr_static, rr_pw, rr_pr, X_pw, y_pw, pairs_X, pairs_y, ep_detail


# =========================================================
# ---- RR helpers
# =========================================================

def _mrr(rrs): return float(np.mean(rrs)) if rrs else float("nan")

def _sub_dk_mrr(rrs, details):
    sub = [r for r, d in zip(rrs, details) if d["sub_dk"]]
    return float(np.mean(sub)) if sub else float("nan")


# =========================================================
# ---- Main experiments
# =========================================================

def run():
    MRR_SEEDS    = [52, 53, 54, 55]
    STRIPE_SEEDS = [62, 63, 64, 65]

    print(f"\n{'='*72}")
    print("Phase 4 V-STaR-lite: pairwise localizer + cross-project transfer")
    print(f"{'='*72}")

    # ----------------------------------------------------------
    # EXP 1: Per-project pairwise (online, same protocol as Ph3)
    # ----------------------------------------------------------
    print("\n--- EXP 1: Online pairwise, per-project ---")
    print("  (train sequentially on each project's own episodes)")

    # mrr-playbook: collect training data then retrain
    freq_mrr: Dict = {}
    clf_pw_mrr, clf_pr_mrr = None, None
    rr_s_m, rr_pw_m, rr_pr_m = [], [], []
    X_pw_m, y_pw_m, pairs_X_m, pairs_y_m = [], [], [], []
    ep_m: List = []

    all_eps_m = []
    for rnd, seed in enumerate(MRR_SEEDS):
        rng = random.Random(seed)
        idx = list(range(len(MRR_EPISODES))); rng.shuffle(idx)
        for ci in idx: all_eps_m.append((rnd + 1, MRR_EPISODES[ci]))

    for ep_idx, (rnd, case) in enumerate(all_eps_m):
        _, _, _, X_pw, y_pw, pX, py, detail = _run_episodes(
            [case], [1], clf_pw_mrr, clf_pr_mrr, freq_mrr, collect=True)
        rr_s_m.extend([d["rr_s"] for d in detail])
        rr_pw_m.extend([d["rr_pw"] for d in detail])
        rr_pr_m.extend([d["rr_pr"] for d in detail])
        X_pw_m.extend(X_pw); y_pw_m.extend(y_pw)
        pairs_X_m.extend(pX); pairs_y_m.extend(py)
        ep_m.extend(detail)
        # Update models after each episode
        clf_pw_mrr = _fit_pointwise(X_pw_m, y_pw_m)
        clf_pr_mrr = _fit_pairwise(pairs_X_m, pairs_y_m)
        # Re-run to get updated RRs
        _, rr_pw_new, rr_pr_new, _, _, _, _, det_new = _run_episodes(
            [case], [1], clf_pw_mrr, clf_pr_mrr, {}, collect=False)
        rr_pw_m[-1] = rr_pw_new[0]
        rr_pr_m[-1] = rr_pr_new[0]
        ep_m[-1]["rr_pw"] = round(rr_pw_new[0], 3)
        ep_m[-1]["rr_pr"] = round(rr_pr_new[0], 3)

    # Simpler approach: run all at once to get final trained models
    _, _, _, X_pw_m_all, y_pw_m_all, pairs_X_m_all, pairs_y_m_all, _ = _run_episodes(
        MRR_EPISODES, MRR_SEEDS, collect=True)
    clf_pw_mrr_final = _fit_pointwise(X_pw_m_all, y_pw_m_all)
    clf_pr_mrr_final = _fit_pairwise(pairs_X_m_all, pairs_y_m_all)

    # stripe: same
    _, _, _, X_pw_s_all, y_pw_s_all, pairs_X_s_all, pairs_y_s_all, _ = _run_episodes(
        STRIPE_EPISODES, STRIPE_SEEDS, collect=True)
    clf_pw_stripe_final = _fit_pointwise(X_pw_s_all, y_pw_s_all)
    clf_pr_stripe_final = _fit_pairwise(pairs_X_s_all, pairs_y_s_all)

    # Evaluate per-project with final trained models
    rr_s_mfin, rr_pw_mfin, rr_pr_mfin, _, _, _, _, ep_mfin = _run_episodes(
        MRR_EPISODES, MRR_SEEDS, clf_pw_mrr_final, clf_pr_mrr_final, collect=False)
    rr_s_sfin, rr_pw_sfin, rr_pr_sfin, _, _, _, _, ep_sfin = _run_episodes(
        STRIPE_EPISODES, STRIPE_SEEDS, clf_pw_stripe_final, clf_pr_stripe_final, collect=False)

    # Phase 3 reference numbers (from published results)
    ph3_mrr_pointwise  = 0.972
    ph3_mrr_sub_dk     = 1.000
    ph3_stripe_pw      = 0.951
    ph3_stripe_sub_dk  = 0.938

    print(f"\n  mrr-playbook (train=mrr, test=mrr, n=36):")
    print(f"  {'Method':<22} {'MRR_full':>9}  {'MRR_sub_dk':>10}")
    print(f"  {'-'*44}")
    print(f"  {'static':<22} {_mrr(rr_s_mfin):>9.3f}  {_sub_dk_mrr(rr_s_mfin,ep_mfin):>10.3f}")
    print(f"  {'pointwise (Ph3 ref)':<22} {ph3_mrr_pointwise:>9.3f}  {ph3_mrr_sub_dk:>10.3f}")
    print(f"  {'pointwise (Ph4)':<22} {_mrr(rr_pw_mfin):>9.3f}  {_sub_dk_mrr(rr_pw_mfin,ep_mfin):>10.3f}")
    print(f"  {'pairwise (Ph4)':<22} {_mrr(rr_pr_mfin):>9.3f}  {_sub_dk_mrr(rr_pr_mfin,ep_mfin):>10.3f}")

    print(f"\n  stripe (train=stripe, test=stripe, n=24):")
    print(f"  {'Method':<22} {'MRR_full':>9}  {'MRR_sub_dk':>10}")
    print(f"  {'-'*44}")
    print(f"  {'static':<22} {_mrr(rr_s_sfin):>9.3f}  {_sub_dk_mrr(rr_s_sfin,ep_sfin):>10.3f}")
    print(f"  {'pointwise (Ph3 ref)':<22} {ph3_stripe_pw:>9.3f}  {ph3_stripe_sub_dk:>10.3f}")
    print(f"  {'pointwise (Ph4)':<22} {_mrr(rr_pw_sfin):>9.3f}  {_sub_dk_mrr(rr_pw_sfin,ep_sfin):>10.3f}")
    print(f"  {'pairwise (Ph4)':<22} {_mrr(rr_pr_sfin):>9.3f}  {_sub_dk_mrr(rr_pr_sfin,ep_sfin):>10.3f}")

    # ----------------------------------------------------------
    # EXP 2: Cross-project zero-shot transfer
    # ----------------------------------------------------------
    print("\n--- EXP 2: Cross-project zero-shot transfer ---")
    print("  (train on project A, evaluate on project B without any B training)")

    # Train on mrr-playbook → test on stripe (zero-shot)
    rr_s_xms, rr_pw_xms, rr_pr_xms, _, _, _, _, ep_xms = _run_episodes(
        STRIPE_EPISODES, STRIPE_SEEDS,
        clf_pw_mrr_final, clf_pr_mrr_final,
        collect=False)

    # Train on stripe → test on mrr-playbook (zero-shot)
    rr_s_xsm, rr_pw_xsm, rr_pr_xsm, _, _, _, _, ep_xsm = _run_episodes(
        MRR_EPISODES, MRR_SEEDS,
        clf_pw_stripe_final, clf_pr_stripe_final,
        collect=False)

    print(f"\n  mrr->stripe zero-shot (train=mrr, test=stripe):")
    print(f"  {'Method':<22} {'MRR_full':>9}  {'MRR_sub_dk':>10}")
    print(f"  {'-'*44}")
    print(f"  {'static':<22} {_mrr(rr_s_xms):>9.3f}  {_sub_dk_mrr(rr_s_xms,ep_xms):>10.3f}")
    print(f"  {'pointwise (Ph3 in-proj)':<22} {ph3_stripe_pw:>9.3f}  {ph3_stripe_sub_dk:>10.3f}")
    print(f"  {'pointwise zero-shot':<22} {_mrr(rr_pw_xms):>9.3f}  {_sub_dk_mrr(rr_pw_xms,ep_xms):>10.3f}")
    print(f"  {'pairwise zero-shot':<22} {_mrr(rr_pr_xms):>9.3f}  {_sub_dk_mrr(rr_pr_xms,ep_xms):>10.3f}")

    print(f"\n  stripe->mrr zero-shot (train=stripe, test=mrr):")
    print(f"  {'Method':<22} {'MRR_full':>9}  {'MRR_sub_dk':>10}")
    print(f"  {'-'*44}")
    print(f"  {'static':<22} {_mrr(rr_s_xsm):>9.3f}  {_sub_dk_mrr(rr_s_xsm,ep_xsm):>10.3f}")
    print(f"  {'pointwise (Ph3 in-proj)':<22} {ph3_mrr_pointwise:>9.3f}  {ph3_mrr_sub_dk:>10.3f}")
    print(f"  {'pointwise zero-shot':<22} {_mrr(rr_pw_xsm):>9.3f}  {_sub_dk_mrr(rr_pw_xsm,ep_xsm):>10.3f}")
    print(f"  {'pairwise zero-shot':<22} {_mrr(rr_pr_xsm):>9.3f}  {_sub_dk_mrr(rr_pr_xsm,ep_xsm):>10.3f}")

    # ----------------------------------------------------------
    # EXP 3: Joint training
    # ----------------------------------------------------------
    print("\n--- EXP 3: Joint training on both projects ---")

    # Combine all training data
    X_pw_joint  = X_pw_m_all  + X_pw_s_all
    y_pw_joint  = y_pw_m_all  + y_pw_s_all
    pairs_X_j   = pairs_X_m_all + pairs_X_s_all
    pairs_y_j   = pairs_y_m_all + pairs_y_s_all

    clf_pw_joint = _fit_pointwise(X_pw_joint, y_pw_joint)
    clf_pr_joint = _fit_pairwise(pairs_X_j,   pairs_y_j)

    rr_s_jm, rr_pw_jm, rr_pr_jm, _, _, _, _, ep_jm = _run_episodes(
        MRR_EPISODES, MRR_SEEDS, clf_pw_joint, clf_pr_joint, collect=False)
    rr_s_js, rr_pw_js, rr_pr_js, _, _, _, _, ep_js = _run_episodes(
        STRIPE_EPISODES, STRIPE_SEEDS, clf_pw_joint, clf_pr_joint, collect=False)

    print(f"\n  Joint -> mrr-playbook (train=both, test=mrr):")
    print(f"  {'Method':<22} {'MRR_full':>9}  {'MRR_sub_dk':>10}")
    print(f"  {'-'*44}")
    print(f"  {'static':<22} {_mrr(rr_s_jm):>9.3f}  {_sub_dk_mrr(rr_s_jm,ep_jm):>10.3f}")
    print(f"  {'Ph3 in-proj ref':<22} {ph3_mrr_pointwise:>9.3f}  {ph3_mrr_sub_dk:>10.3f}")
    print(f"  {'pointwise joint':<22} {_mrr(rr_pw_jm):>9.3f}  {_sub_dk_mrr(rr_pw_jm,ep_jm):>10.3f}")
    print(f"  {'pairwise joint':<22} {_mrr(rr_pr_jm):>9.3f}  {_sub_dk_mrr(rr_pr_jm,ep_jm):>10.3f}")

    print(f"\n  Joint -> stripe (train=both, test=stripe):")
    print(f"  {'Method':<22} {'MRR_full':>9}  {'MRR_sub_dk':>10}")
    print(f"  {'-'*44}")
    print(f"  {'static':<22} {_mrr(rr_s_js):>9.3f}  {_sub_dk_mrr(rr_s_js,ep_js):>10.3f}")
    print(f"  {'Ph3 in-proj ref':<22} {ph3_stripe_pw:>9.3f}  {ph3_stripe_sub_dk:>10.3f}")
    print(f"  {'pointwise joint':<22} {_mrr(rr_pw_js):>9.3f}  {_sub_dk_mrr(rr_pw_js,ep_js):>10.3f}")
    print(f"  {'pairwise joint':<22} {_mrr(rr_pr_js):>9.3f}  {_sub_dk_mrr(rr_pr_js,ep_js):>10.3f}")

    # ----------------------------------------------------------
    # Feature weights comparison
    # ----------------------------------------------------------
    print(f"\n--- Feature weight comparison ---")
    def _print_w(clf, label):
        if clf is None: print(f"  {label}: no model"); return
        w = clf.coef_[0]
        pairs_w = sorted(zip(FEAT_NAMES, w), key=lambda x: -abs(x[1]))
        print(f"  {label}:")
        for n, wt in pairs_w[:6]:
            print(f"    {n:<22}: {wt:+.3f}")

    _print_w(clf_pw_joint,   "pointwise joint")
    _print_w(clf_pr_joint,   "pairwise joint")

    # ----------------------------------------------------------
    # Cross-project transfer analysis
    # ----------------------------------------------------------
    mrr_xms_pw  = _mrr(rr_pw_xms)
    mrr_xms_pr  = _mrr(rr_pr_xms)
    mrr_xsm_pw  = _mrr(rr_pw_xsm)
    mrr_xsm_pr  = _mrr(rr_pr_xsm)
    sub_xms_pr  = _sub_dk_mrr(rr_pr_xms, ep_xms)
    sub_xsm_pr  = _sub_dk_mrr(rr_pr_xsm, ep_xsm)

    # Transfer gap: zero-shot pairwise vs in-project Phase 3
    gap_xms = ph3_stripe_pw  - mrr_xms_pr
    gap_xsm = ph3_mrr_pointwise - mrr_xsm_pr

    print(f"\n{'='*72}")
    print(f"CROSS-PROJECT TRANSFER SUMMARY")
    print(f"  mrr->stripe: pairwise zero-shot MRR = {mrr_xms_pr:.3f}  "
          f"(in-proj Ph3 = {ph3_stripe_pw:.3f}, gap = {gap_xms:+.3f})")
    print(f"  stripe->mrr: pairwise zero-shot MRR = {mrr_xsm_pr:.3f}  "
          f"(in-proj Ph3 = {ph3_mrr_pointwise:.3f}, gap = {gap_xsm:+.3f})")
    print(f"  mrr->stripe sub_dk zero-shot: {sub_xms_pr:.3f}  "
          f"(in-proj sub_dk = {ph3_stripe_sub_dk:.3f})")
    print(f"  stripe->mrr sub_dk zero-shot: {sub_xsm_pr:.3f}  "
          f"(in-proj sub_dk = {ph3_mrr_sub_dk:.3f})")

    if gap_xms <= DELTA and gap_xsm <= DELTA:
        transfer_verdict = "CE_UNIVERSAL"
        interp = ("Zero-shot cross-project gap <= 0.05 in both directions. "
                  "The construction-embedded oracle produces a universal signal: "
                  "structural features learned from one project generalize without retraining.")
    elif max(gap_xms, gap_xsm) <= 0.15:
        transfer_verdict = "CE_PARTIAL"
        interp = ("Zero-shot gap <= 0.15. Partial transfer: CE oracle produces "
                  "portable signal but in-project training retains an advantage "
                  "from project-specific feature statistics.")
    else:
        transfer_verdict = "CE_PROJECT_SPECIFIC"
        interp = ("Large zero-shot gap. The CE oracle's signal is project-specific: "
                  "the structural features are not universal enough for zero-shot transfer.")

    print(f"\n  Transfer verdict : {transfer_verdict}")
    print(f"  Interpretation   : {interp}")
    print(f"{'='*72}")

    # ---- Save ----
    result = {
        "exp1_mrr_per_project": {
            "mrr_pointwise_ph4": _mrr(rr_pw_mfin),
            "mrr_pairwise_ph4":  _mrr(rr_pr_mfin),
            "sub_dk_pointwise":  _sub_dk_mrr(rr_pw_mfin, ep_mfin),
            "sub_dk_pairwise":   _sub_dk_mrr(rr_pr_mfin, ep_mfin),
        },
        "exp1_stripe_per_project": {
            "mrr_pointwise_ph4": _mrr(rr_pw_sfin),
            "mrr_pairwise_ph4":  _mrr(rr_pr_sfin),
            "sub_dk_pointwise":  _sub_dk_mrr(rr_pw_sfin, ep_sfin),
            "sub_dk_pairwise":   _sub_dk_mrr(rr_pr_sfin, ep_sfin),
        },
        "exp2_mrr_to_stripe_zeroshot": {
            "mrr_pointwise": mrr_xms_pw, "mrr_pairwise": mrr_xms_pr,
            "sub_dk_pairwise": sub_xms_pr, "gap_vs_inproject": gap_xms,
        },
        "exp2_stripe_to_mrr_zeroshot": {
            "mrr_pointwise": mrr_xsm_pw, "mrr_pairwise": mrr_xsm_pr,
            "sub_dk_pairwise": sub_xsm_pr, "gap_vs_inproject": gap_xsm,
        },
        "exp3_joint": {
            "mrr_pointwise_mrr": _mrr(rr_pw_jm), "mrr_pairwise_mrr": _mrr(rr_pr_jm),
            "mrr_pointwise_str": _mrr(rr_pw_js), "mrr_pairwise_str": _mrr(rr_pr_js),
            "sub_dk_pairwise_mrr": _sub_dk_mrr(rr_pr_jm, ep_jm),
            "sub_dk_pairwise_str": _sub_dk_mrr(rr_pr_js, ep_js),
        },
        "transfer_verdict":  transfer_verdict,
        "interpretation":    interp,
        "pw_joint_weights":  (dict(zip(FEAT_NAMES, clf_pw_joint.coef_[0].tolist()))
                              if clf_pw_joint else None),
        "pr_joint_weights":  (dict(zip(FEAT_NAMES, clf_pr_joint.coef_[0].tolist()))
                              if clf_pr_joint else None),
    }
    OUT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"\nResults saved: {OUT}")
    return result


if __name__ == "__main__":
    run()
