"""
dbt_phase3_alias.py -- Phase 3: alias_in_hunk feature on mrr-playbook.

Feature added: alias_in_hunk = 1 if the candidate's output alias appears in
the diff hunk's changed lines (for SELECT candidates) or if the candidate's
joined table name appears anywhere in the hunk (for JOIN candidates).

Goal: Test whether column-level diff context resolves sub-diff_kind ambiguity
(cases where two candidates share diff_kind_match=1 AND exact_match=1 but are
different expressions).

Pre-committed verdict bands:
  GREEN  : learned_3 beats learned_2b by >= 0.05 MRR on the sub-diff_kind subset
  YELLOW : learned_3 improves sub-dk subset but delta < 0.05
  RED    : learned_3 does not improve sub-diff_kind subset (delta <= 0)

Sub-diff_kind subset = {m_crm01, m_crm02}:
  Both candidates are agg type with exact_match=1, so diff_kind_match is
  identical for both and cannot separate them.  alias_in_hunk differs:
  m_crm01 hunk has 'AS date_month_start' (true=e_min_start, decoy=e_max_end);
  m_crm02 hunk has 'AS date_month_end'   (true=e_max_end,   decoy=e_min_start).
"""

import json
import re
import random
import pathlib
from typing import Dict, List, Tuple

import numpy as np
from diff_parser import classify_diff_kind, _split_hunk

HERE = pathlib.Path(__file__).resolve().parent
OUT  = HERE / "dbt_phase3_alias_results.json"

DELTA       = 0.05
N_ROUNDS    = 4
ROUND_SEEDS = [52, 53, 54, 55]

# ---- expression candidates ----

CRM_MODEL = "models/customer_revenue_by_month.sql"
MRR_MODEL = "models/mrr.sql"
CCM_MODEL = "models/customer_churn_month.sql"

_MODEL_N_COLS = {
    CRM_MODEL: 8,
    MRR_MODEL: 14,
    CCM_MODEL: 8,
}

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

# alias: output alias of the SELECT expression (e.g. "AS date_month_start")
# joined_table: table name in the JOIN clause (e.g. "months")
EXPRESSION_CANDIDATES = {
    CRM_MODEL: [
        {"expr_id": "e_min_start",
         "feeds_cols": _CRM_SPINE_COLS,
         "is_agg": True,  "is_join": False, "line": 18,
         "alias": "date_month_start", "joined_table": ""},
        {"expr_id": "e_max_end",
         "feeds_cols": _CRM_SPINE_COLS,
         "is_agg": True,  "is_join": False, "line": 19,
         "alias": "date_month_end", "joined_table": ""},
        {"expr_id": "e_cm_join",
         "feeds_cols": _CRM_SPINE_COLS,
         "is_agg": False, "is_join": True,  "line": 37,
         "alias": "", "joined_table": "months"},
        {"expr_id": "e_sub_join",
         "feeds_cols": _CRM_VALUE_COLS,
         "is_agg": False, "is_join": True,  "line": 56,
         "alias": "", "joined_table": "subscription_periods"},
        {"expr_id": "e_coalesce_mrr",
         "feeds_cols": _CRM_VALUE_COLS,
         "is_agg": False, "is_join": False, "line": 52,
         "alias": "mrr", "joined_table": ""},
    ],
    MRR_MODEL: [
        {"expr_id": "e_lag_mrr",
         "feeds_cols": frozenset(["previous_month_mrr", "mrr_change",
                                   "change_category", "renewal_amount"]),
         "is_agg": False, "is_join": False, "line": 23,
         "alias": "previous_month_mrr", "joined_table": ""},
        {"expr_id": "e_mrr_change",
         "feeds_cols": frozenset(["mrr_change", "change_category"]),
         "is_agg": False, "is_join": False, "line": 27,
         "alias": "mrr_change", "joined_table": ""},
        {"expr_id": "e_renewal",
         "feeds_cols": frozenset(["renewal_amount"]),
         "is_agg": False, "is_join": False, "line": 53,
         "alias": "renewal_amount", "joined_table": ""},
    ],
    CCM_MODEL: [
        {"expr_id": "e_ccm_date",
         "feeds_cols": frozenset(["date_month"]),
         "is_agg": False, "is_join": False, "line": 11,
         "alias": "date_month", "joined_table": ""},
    ],
}

# ---- diff hunks (same as Phase 2b transfer) ----

MRR_DIFFS = {
    "m_crm01": """\
@@ -16,5 +16,5 @@
     select
         customer_id,
-        date_trunc('month', min(start_date)) as date_month_start,
+        date_trunc('month', min(start_date + 1)) as date_month_start,
         date_trunc('month', max(end_date)) as date_month_end
""",
    "m_crm02": """\
@@ -17,5 +17,5 @@
         customer_id,
         date_trunc('month', min(start_date)) as date_month_start,
-        date_trunc('month', max(end_date)) as date_month_end
+        date_trunc('month', max(end_date + 1)) as date_month_end

     from subscription_periods
""",
    "m_crm03": """\
@@ -37,6 +37,6 @@
     inner join months
         -- all months after start date
-        on  months.date_month >= customers.date_month_start
+        on  months.date_month > customers.date_month_start
         -- and before end date
         and months.date_month < customers.date_month_end
""",
    "m_crm04": """\
@@ -56,6 +56,6 @@
     left join subscription_periods
-        on customer_months.customer_id = subscription_periods.customer_id
+        on customer_months.customer_id != subscription_periods.customer_id
         -- month is after a subscription start date
         and customer_months.date_month >= subscription_periods.start_date
""",
    "m_crm05": """\
@@ -49,5 +49,5 @@
         customer_months.date_month,
         customer_months.customer_id,
-        coalesce(subscription_periods.monthly_amount, 0) as mrr
+        coalesce(subscription_periods.monthly_amount, 1) as mrr

     from customer_months
""",
    "m_mrr01": """\
@@ -21,5 +21,5 @@
         coalesce(
-            lag(mrr) over (partition by customer_id order by date_month),
+            lag(mrr, 2) over (partition by customer_id order by date_month),
             0
         ) as previous_month_mrr,
""",
    "m_mrr02": """\
@@ -25,5 +25,5 @@
         ) as previous_month_mrr,

-        mrr - previous_month_mrr as mrr_change
+        mrr - previous_month_mrr - 1 as mrr_change

     from unioned
""",
    "m_mrr03": """\
@@ -51,5 +51,5 @@

-        least(mrr, previous_month_mrr) as renewal_amount
+        greatest(mrr, previous_month_mrr) as renewal_amount

     from mrr_with_changes
""",
    "m_ccm01": """\
@@ -9,5 +9,5 @@
     select
-        dateadd(month, 1, date_month)::date as date_month,
+        dateadd(month, 2, date_month)::date as date_month,
         customer_id,
""",
}

_EXPECTED_KINDS = {
    "m_crm01": "agg", "m_crm02": "agg", "m_crm03": "join",
    "m_crm04": "join", "m_crm05": "unknown",
    "m_mrr01": "unknown", "m_mrr02": "arithmetic",
    "m_mrr03": "unknown", "m_ccm01": "unknown",
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
# sub_dk=True: cases where the true candidate AND >= 1 incorrect candidate
# BOTH have diff_kind_match=1 AND exact_match=1, so diff_kind_match cannot
# separate them.  alias_in_hunk is the candidate resolution.

_SPINE_DIV = frozenset(["date_month", "mrr", "is_active",
                          "first_active_month", "last_active_month",
                          "is_first_month", "is_last_month"])
_VALUE_DIV = frozenset(["mrr", "is_active",
                          "first_active_month", "last_active_month",
                          "is_first_month", "is_last_month"])

EPISODE_CASES = [
    {"case_id": "m_crm01", "model_rel": CRM_MODEL, "true_eid": "e_min_start",
     "div_cols": _SPINE_DIV, "diff_id": "m_crm01", "amb": True,  "sub_dk": True},
    {"case_id": "m_crm02", "model_rel": CRM_MODEL, "true_eid": "e_max_end",
     "div_cols": _SPINE_DIV, "diff_id": "m_crm02", "amb": True,  "sub_dk": True},
    {"case_id": "m_crm03", "model_rel": CRM_MODEL, "true_eid": "e_cm_join",
     "div_cols": _SPINE_DIV, "diff_id": "m_crm03", "amb": True,  "sub_dk": False},
    {"case_id": "m_crm04", "model_rel": CRM_MODEL, "true_eid": "e_sub_join",
     "div_cols": _VALUE_DIV, "diff_id": "m_crm04", "amb": True,  "sub_dk": False},
    {"case_id": "m_crm05", "model_rel": CRM_MODEL, "true_eid": "e_coalesce_mrr",
     "div_cols": _VALUE_DIV, "diff_id": "m_crm05", "amb": True,  "sub_dk": False},
    {"case_id": "m_mrr01", "model_rel": MRR_MODEL, "true_eid": "e_lag_mrr",
     "div_cols": frozenset(["previous_month_mrr", "mrr_change",
                             "change_category", "renewal_amount"]),
     "diff_id": "m_mrr01", "amb": False, "sub_dk": False},
    {"case_id": "m_mrr02", "model_rel": MRR_MODEL, "true_eid": "e_mrr_change",
     "div_cols": frozenset(["mrr_change", "change_category"]),
     "diff_id": "m_mrr02", "amb": False, "sub_dk": False},
    {"case_id": "m_mrr03", "model_rel": MRR_MODEL, "true_eid": "e_renewal",
     "div_cols": frozenset(["renewal_amount"]),
     "diff_id": "m_mrr03", "amb": False, "sub_dk": False},
    {"case_id": "m_ccm01", "model_rel": CCM_MODEL, "true_eid": "e_ccm_date",
     "div_cols": frozenset(["date_month"]),
     "diff_id": "m_ccm01", "amb": False, "sub_dk": False},
]

N_CASES     = len(EPISODE_CASES)
CHECKPOINTS = [N_CASES, N_CASES * 2, N_CASES * 3, N_CASES * N_ROUNDS]


# ---- candidate filtering ----

def _get_cands(model_rel: str, diverged_cols) -> List[dict]:
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


# ---- alias_in_hunk feature ----

def _alias_in_hunk(cand: dict, hunk: str) -> float:
    """
    Returns 1.0 if the candidate's identifying token appears in the diff hunk:
    - SELECT candidates (is_join=False): search for 'AS <alias>' in changed lines only.
    - JOIN candidates (is_join=True): search for joined_table name in full hunk
      (JOIN keyword is often on a context line, ON clause on the changed line).
    """
    changed, full = _split_hunk(hunk)
    if cand["is_join"]:
        tbl = cand.get("joined_table", "")
        if not tbl:
            return 0.0
        return float(bool(re.search(r'\b' + re.escape(tbl) + r'\b', full, re.IGNORECASE)))
    else:
        alias = cand.get("alias", "")
        if not alias:
            return 0.0
        pat = r'\bAS\s+' + re.escape(alias) + r'\b'
        return float(bool(re.search(pat, changed, re.IGNORECASE)))


# ---- feature extraction ----

def _candidate_features(cand: dict, diverged_cols, row_count_changed: bool,
                         model_rel: str, freq_ctx: Dict = None) -> List[float]:
    """10-feature base vector (same as Phase 2a)."""
    div_set   = frozenset(diverged_cols)
    feeds     = cand["feeds_cols"]
    n_div     = len(div_set)
    n_total   = _MODEL_N_COLS.get(model_rel, max(n_div, 1))
    all_cands = EXPRESSION_CANDIDATES.get(model_rel, [cand])
    max_feeds = max(len(c["feeds_cols"]) for c in all_cands)

    exact      = float(feeds == div_set)
    superset   = float(div_set <= feeds)
    overlap    = float(len(feeds & div_set) > 0)
    is_join    = float(cand["is_join"])
    is_agg     = float(cand["is_agg"])
    feeds_norm = len(feeds) / max(max_feeds, 1)
    n_div_norm = n_div / max(n_total, 1)
    row_ct     = float(row_count_changed)
    single     = float(n_div == 1)

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


def _features_3(cand: dict, diverged_cols, row_count_changed: bool,
                 model_rel: str, diff_kind: str,
                 freq_ctx: Dict = None, hunk: str = "") -> List[float]:
    """12-feature vector (Phase 3): Phase 2b features + alias_in_hunk."""
    base        = _features_2b(cand, diverged_cols, row_count_changed,
                                model_rel, diff_kind, freq_ctx)
    alias_feat  = _alias_in_hunk(cand, hunk)
    return base + [alias_feat]


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
                   hunk: str = "",
                   use_2b: bool = False,
                   use_3: bool = False) -> List[int]:
    if clf is None:
        return static_order[:]

    if use_3 and diff_kind is not None:
        feats = [_features_3(c, diverged_cols, row_count_changed,
                              model_rel, diff_kind, freq_ctx, hunk)
                 for c in cands]
    elif use_2b and diff_kind is not None:
        feats = [_features_2b(c, diverged_cols, row_count_changed,
                               model_rel, diff_kind, freq_ctx)
                 for c in cands]
    else:
        feats = [_candidate_features(c, diverged_cols, row_count_changed,
                                     model_rel, freq_ctx)
                 for c in cands]

    try:
        scores = clf.predict_proba(feats)[:, 1]
    except Exception:
        return static_order[:]

    return sorted(range(len(cands)), key=lambda i: (-scores[i], static_order.index(i)))


# ---- MRR helpers ----

def _rr(rank_order: List[int], true_idx: int) -> float:
    try:
        return 1.0 / (rank_order.index(true_idx) + 1)
    except ValueError:
        return 0.0


# ---- alias feature pre-flight ----

def _print_alias_features():
    """Print alias_in_hunk value for each candidate in each case."""
    print("alias_in_hunk pre-flight (expected: true candidate unique where sub_dk=True):")
    for case in EPISODE_CASES:
        case_id  = case["case_id"]
        hunk     = MRR_DIFFS[case["diff_id"]]
        cands    = _get_cands(case["model_rel"], case["div_cols"])
        true_eid = case["true_eid"]
        feats    = [(c["expr_id"], _alias_in_hunk(c, hunk)) for c in cands]
        true_val = next((v for eid, v in feats if eid == true_eid), 0.0)
        others_1 = [eid for eid, v in feats if eid != true_eid and v == 1.0]
        if true_val == 1.0 and not others_1:
            tag = "UNIQUE"
        elif true_val == 1.0:
            tag = f"TIE({','.join(others_1)})"
        else:
            tag = "NOT_IN_HUNK"
        feat_str = "  ".join(f"{eid}={v:.0f}" for eid, v in feats)
        sdk_tag  = " [sub_dk]" if case["sub_dk"] else ""
        print(f"  {case_id:<10}{sdk_tag:<9} {feat_str}  -> {tag}")


# ---- main simulation ----

def run_simulation():
    print("\nValidating diff hunk classifications:")
    if not _validate_diffs():
        raise RuntimeError("Diff validation failed.")
    print()

    _print_alias_features()
    print()

    all_episodes = []
    for rnd, seed in enumerate(ROUND_SEEDS):
        rng     = random.Random(seed)
        indices = list(range(N_CASES))
        rng.shuffle(indices)
        for case_idx in indices:
            all_episodes.append((rnd + 1, EPISODE_CASES[case_idx]))

    total_eps = len(all_episodes)
    print(f"Detectable mutations : {N_CASES}")
    print(f"Total episodes       : {total_eps}")

    # State
    freq_ctx: Dict[Tuple, Dict[str, Tuple[int, int]]] = {}
    X_2b: List[List[float]] = []
    y_2b: List[int]          = []
    X_3:  List[List[float]] = []
    y_3:  List[int]          = []
    clf_2b = None
    clf_3  = None

    # Accumulators
    rr_static = []
    rr_freq   = []
    rrs_2b    = []
    rrs_3     = []
    ep_detail = []

    print(f"\n{'='*72}")
    print(f"Phase 3 alias_in_hunk -- mrr-playbook")
    print(f"GREEN: learned_3 beats learned_2b by >= {DELTA} MRR on sub-dk subset")
    print(f"Sub-dk subset: m_crm01 + m_crm02  (both-agg ambiguity, diff_kind_match tied)")
    print(f"{'='*72}")

    for ep_idx, (rnd, case) in enumerate(all_episodes):
        case_id   = case["case_id"]
        model_rel = case["model_rel"]
        true_eid  = case["true_eid"]
        div_cols  = case["div_cols"]
        hunk      = MRR_DIFFS[case["diff_id"]]

        diff_kind    = classify_diff_kind(hunk)
        row_ct       = False
        div_set      = frozenset(div_cols)
        cands        = _get_cands(model_rel, div_cols)
        static_order = _rank_static(cands, div_cols)
        true_idx     = next((i for i, c in enumerate(cands)
                             if c["expr_id"] == true_eid), 0)

        freq_order = _rank_frequency(cands, freq_ctx, div_cols,
                                      model_rel, static_order)
        learned_2b = _rank_learned(cands, div_cols, row_ct, model_rel,
                                    clf_2b, static_order, freq_ctx,
                                    diff_kind=diff_kind, use_2b=True)
        learned_3  = _rank_learned(cands, div_cols, row_ct, model_rel,
                                    clf_3, static_order, freq_ctx,
                                    diff_kind=diff_kind, hunk=hunk, use_3=True)

        rr_s  = _rr(static_order, true_idx)
        rr_f  = _rr(freq_order,   true_idx)
        rr_2b = _rr(learned_2b,   true_idx)
        rr_3  = _rr(learned_3,    true_idx)

        rr_static.append(rr_s)
        rr_freq.append(rr_f)
        rrs_2b.append(rr_2b)
        rrs_3.append(rr_3)

        ep_detail.append({
            "ep": ep_idx + 1, "rnd": rnd,
            "case_id": case_id, "diff_kind": diff_kind,
            "amb": case["amb"], "sub_dk": case["sub_dk"],
            "n_cands": len(cands),
            "r_s":  static_order.index(true_idx) + 1,
            "r_f":  freq_order.index(true_idx) + 1,
            "r_2b": learned_2b.index(true_idx) + 1,
            "r_3":  learned_3.index(true_idx)  + 1,
            "rr_s":  round(rr_s,  3), "rr_f":  round(rr_f,  3),
            "rr_2b": round(rr_2b, 3), "rr_3":  round(rr_3,  3),
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

        # Collect training features (post-episode, includes this episode's outcome)
        for c in cands:
            is_correct = int(c["expr_id"] == true_eid)
            X_2b.append(_features_2b(c, div_cols, row_ct, model_rel,
                                      diff_kind, freq_ctx))
            y_2b.append(is_correct)
            X_3.append(_features_3(c, div_cols, row_ct, model_rel,
                                    diff_kind, freq_ctx, hunk))
            y_3.append(is_correct)

        clf_2b = _fit(X_2b, y_2b)
        clf_3  = _fit(X_3,  y_3)

        # Checkpoints
        ep_num = ep_idx + 1
        if ep_num in CHECKPOINTS:
            mrr_s_cp  = float(np.mean(rr_static[:ep_num]))
            mrr_f_cp  = float(np.mean(rr_freq[:ep_num]))
            mrr_2b_cp = float(np.mean(rrs_2b[:ep_num]))
            mrr_3_cp  = float(np.mean(rrs_3[:ep_num]))

            sub_2b_cp = [x for x, d in zip(rrs_2b[:ep_num], ep_detail[:ep_num])
                         if d["sub_dk"]]
            sub_3_cp  = [x for x, d in zip(rrs_3[:ep_num],  ep_detail[:ep_num])
                         if d["sub_dk"]]
            mrr_sub_2b_cp = float(np.mean(sub_2b_cp)) if sub_2b_cp else float("nan")
            mrr_sub_3_cp  = float(np.mean(sub_3_cp))  if sub_3_cp  else float("nan")
            d_sub_cp  = mrr_sub_3_cp - mrr_sub_2b_cp

            if d_sub_cp >= DELTA:
                cp_tag = "GREEN"
            elif d_sub_cp > 0:
                cp_tag = "YELLOW"
            else:
                cp_tag = "RED"

            print(f"\n--- Checkpoint ep {ep_num} (round {rnd}) ---")
            print(f"  {'Method':<14} {'MRR_full':>9}   {'MRR_sub_dk':>10}")
            print(f"  {'-'*38}")
            for label, rrs in [("static",    rr_static),
                                ("frequency", rr_freq),
                                ("learned_2b", rrs_2b),
                                ("learned_3",  rrs_3)]:
                sub   = [x for x, d in zip(rrs[:ep_num], ep_detail[:ep_num]) if d["sub_dk"]]
                m_all = float(np.mean(rrs[:ep_num]))
                m_sub = float(np.mean(sub)) if sub else float("nan")
                print(f"  {label:<14} {m_all:>9.3f}   {m_sub:>10.3f}")
            print(f"  3 vs 2b: delta_full={mrr_3_cp - mrr_2b_cp:+.3f}"
                  f"  delta_sub_dk={d_sub_cp:+.3f}  -> {cp_tag}")

    # ---- Final verdict ----
    mrr_s_f   = float(np.mean(rr_static))
    mrr_f_f   = float(np.mean(rr_freq))
    mrr_2b_f  = float(np.mean(rrs_2b))
    mrr_3_f   = float(np.mean(rrs_3))
    d_full    = mrr_3_f - mrr_2b_f

    sub_2b_all = [x for x, d in zip(rrs_2b, ep_detail) if d["sub_dk"]]
    sub_3_all  = [x for x, d in zip(rrs_3,  ep_detail) if d["sub_dk"]]
    mrr_sub_2b = float(np.mean(sub_2b_all)) if sub_2b_all else float("nan")
    mrr_sub_3  = float(np.mean(sub_3_all))  if sub_3_all  else float("nan")
    d_subset   = mrr_sub_3 - mrr_sub_2b

    if d_subset >= DELTA:
        verdict = "GREEN"
        interp  = ("alias_in_hunk resolves sub-diff_kind ambiguity; "
                   "column-level diff context separates min/max agg candidates")
    elif d_subset > 0:
        verdict = "YELLOW"
        interp  = (f"alias_in_hunk improves sub-dk subset (+{d_subset:.3f}) "
                   f"but below GREEN threshold (delta_full={d_full:+.3f})")
    else:
        verdict = "RED"
        interp  = ("alias_in_hunk does not improve sub-dk subset; "
                   "column-level alias alone insufficient for min/max separation")

    print(f"\n{'='*72}")
    print(f"PHASE 3 VERDICT: {verdict}")
    print(f"  Project                  : dbt-labs/mrr-playbook")
    print(f"  Feature added            : alias_in_hunk")
    print(f"  MRR static               : {mrr_s_f:.3f}")
    print(f"  MRR frequency            : {mrr_f_f:.3f}")
    print(f"  MRR learned_2b           : {mrr_2b_f:.3f}")
    print(f"  MRR learned_3            : {mrr_3_f:.3f}")
    print(f"  delta_3_vs_2b (full MRR) : {d_full:+.3f}")
    print(f"  MRR_sub_dk learned_2b    : {mrr_sub_2b:.3f}  (m_crm01 + m_crm02)")
    print(f"  MRR_sub_dk learned_3     : {mrr_sub_3:.3f}")
    print(f"  delta_3_vs_2b (sub_dk)   : {d_subset:+.3f}  (GREEN >= {DELTA})")
    print(f"  Interpretation           : {interp}")
    print(f"{'='*72}")

    # Sub-dk per-case breakdown
    print(f"\nSub-dk case performance (4 rounds each):")
    for case_id in ("m_crm01", "m_crm02"):
        eps     = [d for d in ep_detail if d["case_id"] == case_id]
        avg_s   = float(np.mean([e["rr_s"]  for e in eps]))
        avg_f   = float(np.mean([e["rr_f"]  for e in eps]))
        avg_2b  = float(np.mean([e["rr_2b"] for e in eps]))
        avg_3   = float(np.mean([e["rr_3"]  for e in eps]))
        true_eid = next(c["true_eid"] for c in EPISODE_CASES if c["case_id"] == case_id)
        dk       = eps[0]["diff_kind"] if eps else "?"
        print(f"  {case_id} (true={true_eid}, diff={dk}): "
              f"static={avg_s:.3f}  freq={avg_f:.3f}  2b={avg_2b:.3f}  3={avg_3:.3f}")

    # Group-A full breakdown
    print(f"\nGroup A (spine cols) case performance:")
    for case_id in ("m_crm01", "m_crm02", "m_crm03"):
        eps    = [d for d in ep_detail if d["case_id"] == case_id]
        avg_s  = float(np.mean([e["rr_s"]  for e in eps]))
        avg_f  = float(np.mean([e["rr_f"]  for e in eps]))
        avg_2b = float(np.mean([e["rr_2b"] for e in eps]))
        avg_3  = float(np.mean([e["rr_3"]  for e in eps]))
        true_eid = next(c["true_eid"] for c in EPISODE_CASES if c["case_id"] == case_id)
        dk = eps[0]["diff_kind"] if eps else "?"
        print(f"  {case_id} (true={true_eid}, diff={dk}): "
              f"static={avg_s:.3f}  freq={avg_f:.3f}  2b={avg_2b:.3f}  3={avg_3:.3f}")

    # Feature weights
    feat_names_2b = ["exact_match", "superset_match", "any_overlap",
                     "is_join", "is_agg", "feeds_norm", "n_div_norm",
                     "row_count_changed", "single_col", "hist_freq",
                     "diff_kind_match"]
    feat_names_3  = feat_names_2b + ["alias_in_hunk"]

    def _print_weights(clf, names, label):
        if clf is None:
            print(f"  {label}: no model")
            return
        w     = clf.coef_[0]
        pairs = sorted(zip(names, w), key=lambda x: -abs(x[1]))
        print(f"  {label}:")
        for name, wt in pairs:
            print(f"    {name:<22} : {wt:+.3f}")

    print(f"\nFinal feature weights:")
    _print_weights(clf_2b, feat_names_2b, "learned_2b")
    _print_weights(clf_3,  feat_names_3,  "learned_3")

    # Per-episode detail
    print(f"\nPer-episode detail:")
    hdr = (f"{'ep':>4} {'rnd':>3} {'case_id':<10} {'dk':<10} "
           f"{'amb':<4} {'sdk':<4} {'nc':>3} "
           f"{'r_s':>4} {'r_f':>4} {'r_2b':>5} {'r_3':>4} "
           f"{'rr_s':>6} {'rr_f':>6} {'rr_2b':>7} {'rr_3':>6}")
    print(f"  {hdr}")
    print(f"  {'-'*90}")
    for d in ep_detail:
        print(f"  {d['ep']:>4} {d['rnd']:>3}  {d['case_id']:<10} "
              f"{d['diff_kind']:<10} "
              f"{'Y' if d['amb'] else 'N':<4} {'Y' if d['sub_dk'] else 'N':<4} "
              f"{d['n_cands']:>3} "
              f"{d['r_s']:>4} {d['r_f']:>4} {d['r_2b']:>5} {d['r_3']:>4} "
              f"{d['rr_s']:>6.3f} {d['rr_f']:>6.3f} "
              f"{d['rr_2b']:>7.3f} {d['rr_3']:>6.3f}")

    # Save
    result = {
        "project": "dbt-labs/mrr-playbook",
        "phase": 3,
        "feature_added": "alias_in_hunk",
        "n_cases": N_CASES, "n_rounds": N_ROUNDS, "total_episodes": total_eps,
        "mrr_static": mrr_s_f, "mrr_freq": mrr_f_f,
        "mrr_2b": mrr_2b_f, "mrr_3": mrr_3_f,
        "delta_3_vs_2b_full": d_full,
        "mrr_sub_dk_2b": mrr_sub_2b, "mrr_sub_dk_3": mrr_sub_3,
        "delta_3_vs_2b_sub_dk": d_subset,
        "verdict": verdict, "interpretation": interp,
        "feature_weights_2b": (
            dict(zip(feat_names_2b, clf_2b.coef_[0].tolist())) if clf_2b else None),
        "feature_weights_3": (
            dict(zip(feat_names_3, clf_3.coef_[0].tolist())) if clf_3 else None),
        "episodes": ep_detail,
    }
    OUT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"\nResults saved: {OUT}")
    return result


if __name__ == "__main__":
    run_simulation()
