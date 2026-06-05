"""
dbt_phase3_stripe.py -- Phase 3 transfer: alias_in_hunk on fivetran/dbt_stripe.

Target  : stripe__invoice_details.sql (CHILD-AGGREGATE-JOIN pattern)
Feature : alias_in_hunk (same as mrr-playbook Phase 3 run)
Stack   : static + frequency + diff_kind_match + alias_in_hunk (no tuning)

Attribution question:
  Do gains come from diff_kind_match, alias_in_hunk, or both?

Pre-committed bands (delta threshold 0.05, same as prior runs):
  Overall:
    GREEN  : learned_3 > static + 0.05 AND > freq + 0.05 (full MRR)
    YELLOW : learned_3 > static + 0.05 AND <= freq + 0.05
    RED    : learned_3 <= static + 0.05
  diff_kind_match gain (Δ_2b_vs_static):
    FIRES  : Δ_2b_vs_static >= 0.05
  alias_in_hunk gain (Δ_sub_dk = MRR_sub_dk_3 - MRR_sub_dk_2b):
    GREEN  : Δ_sub_dk >= +0.05
    YELLOW : Δ_sub_dk in (0, +0.05)
    RED    : Δ_sub_dk <= 0

Sub-dk subset = {s_inv01, s_inv02}:
  Both are agg mutations in the invoice_line_item pre-aggregation CTE.
  Both e_count_lines and e_sum_qty have identical Phase 2b feature vectors
  (same feeds_cols, same diff_kind_match=1). alias_in_hunk is the resolution.
"""

import json
import re
import random
import pathlib
from typing import Dict, List, Tuple

import numpy as np
from diff_parser import classify_diff_kind, _split_hunk

HERE = pathlib.Path(__file__).resolve().parent
OUT  = HERE / "dbt_phase3_stripe_results.json"

DELTA       = 0.05
N_ROUNDS    = 4
ROUND_SEEDS = [62, 63, 64, 65]

# ---- expression candidates ----

STRIPE_MODEL = "models/stripe__invoice_details.sql"

_MODEL_N_COLS = {
    STRIPE_MODEL: 35,
}

_GROUP_A_COLS = frozenset(["number_of_line_items", "total_quantity"])
_GROUP_B_COLS = frozenset(["charge_amount", "charge_status",
                            "charge_created_at", "charge_is_refunded"])
_GROUP_C_COLS = frozenset(["subscription_billing", "subscription_start_date",
                            "subscription_ended_at"])
_GROUP_D_COLS = frozenset(["customer_id", "customer_description",
                            "customer_account_balance", "customer_currency",
                            "customer_is_delinquent", "customer_email"])

EXPRESSION_CANDIDATES = {
    STRIPE_MODEL: [
        # Group A — invoice_line_item metrics (feeds same cols from different layers)
        {"expr_id": "e_count_lines",
         "feeds_cols": _GROUP_A_COLS,
         "is_agg": True, "is_join": False, "line": 18,
         "alias": "number_of_line_items", "joined_table": ""},
        {"expr_id": "e_sum_qty",
         "feeds_cols": _GROUP_A_COLS,
         "is_agg": True, "is_join": False, "line": 19,
         "alias": "total_quantity", "joined_table": ""},
        {"expr_id": "e_join_ili",
         "feeds_cols": _GROUP_A_COLS,
         "is_agg": False, "is_join": True, "line": 91,
         "alias": "", "joined_table": "invoice_line_item"},
        # Groups B-D — single-candidate pools (non-overlapping feeds_cols)
        {"expr_id": "e_join_charge",
         "feeds_cols": _GROUP_B_COLS,
         "is_agg": False, "is_join": True, "line": 95,
         "alias": "", "joined_table": "charge"},
        {"expr_id": "e_join_sub",
         "feeds_cols": _GROUP_C_COLS,
         "is_agg": False, "is_join": True, "line": 101,
         "alias": "", "joined_table": "subscription"},
        {"expr_id": "e_join_cust",
         "feeds_cols": _GROUP_D_COLS,
         "is_agg": False, "is_join": True, "line": 107,
         "alias": "", "joined_table": "customer"},
    ],
}

# ---- synthetic diff hunks (from PHASE3-TRANSFER-precommit.md) ----

STRIPE_DIFFS = {
    # s_inv01: invoice_line_item CTE -- mutate count(distinct ...) [agg]
    "s_inv01": """\
@@ -16,6 +16,6 @@
     select
         invoice_id,
         source_relation,
-        coalesce(count(distinct unique_invoice_line_item_id),0) as number_of_line_items,
+        coalesce(count(unique_invoice_line_item_id),0) as number_of_line_items,
         coalesce(sum(quantity),0) as total_quantity
""",

    # s_inv02: invoice_line_item CTE -- mutate sum(quantity) [agg]
    "s_inv02": """\
@@ -17,6 +17,6 @@
         invoice_id,
         source_relation,
         coalesce(count(distinct unique_invoice_line_item_id),0) as number_of_line_items,
-        coalesce(sum(quantity),0) as total_quantity
+        coalesce(sum(quantity * 2),0) as total_quantity

""",

    # s_inv03: final SELECT -- mutate left join invoice_line_item ON condition [join]
    "s_inv03": """\
@@ -91,5 +91,5 @@
 left join invoice_line_item
-    on invoice.invoice_id = invoice_line_item.invoice_id
+    on invoice.invoice_id != invoice_line_item.invoice_id
     and invoice.source_relation = invoice_line_item.source_relation
""",

    # s_inv04: final SELECT -- mutate left join charge ON condition [join]
    "s_inv04": """\
@@ -96,5 +96,5 @@
 left join charge
-    on invoice.charge_id = charge.charge_id
+    on invoice.charge_id != charge.charge_id
     and invoice.invoice_id = charge.invoice_id
""",

    # s_inv05: final SELECT -- mutate left join subscription ON condition [join]
    "s_inv05": """\
@@ -101,5 +101,5 @@
 left join subscription
-    on invoice.subscription_id = subscription.subscription_id
+    on invoice.subscription_id != subscription.subscription_id
     and invoice.source_relation = subscription.source_relation
""",

    # s_inv06: final SELECT -- mutate left join customer ON condition [join]
    "s_inv06": """\
@@ -107,5 +107,5 @@
 left join customer
-    on invoice.customer_id = customer.customer_id
+    on invoice.customer_id != customer.customer_id
     and invoice.source_relation = customer.source_relation
""",
}

_EXPECTED_KINDS = {
    "s_inv01": "agg",
    "s_inv02": "agg",
    "s_inv03": "join",
    "s_inv04": "join",
    "s_inv05": "join",
    "s_inv06": "join",
}


def _validate_diffs() -> bool:
    ok = True
    for cid, expected in _EXPECTED_KINDS.items():
        got    = classify_diff_kind(STRIPE_DIFFS[cid])
        status = "OK" if got == expected else "FAIL"
        print(f"  {cid:<10} expected={expected:<8} got={got:<8} {status}")
        if got != expected:
            ok = False
    return ok


# ---- episode cases ----

EPISODE_CASES = [
    # Group A — pool = {e_count_lines, e_sum_qty, e_join_ili}
    {"case_id": "s_inv01", "model_rel": STRIPE_MODEL, "true_eid": "e_count_lines",
     "div_cols": _GROUP_A_COLS, "diff_id": "s_inv01", "amb": True,  "sub_dk": True},
    {"case_id": "s_inv02", "model_rel": STRIPE_MODEL, "true_eid": "e_sum_qty",
     "div_cols": _GROUP_A_COLS, "diff_id": "s_inv02", "amb": True,  "sub_dk": True},
    {"case_id": "s_inv03", "model_rel": STRIPE_MODEL, "true_eid": "e_join_ili",
     "div_cols": _GROUP_A_COLS, "diff_id": "s_inv03", "amb": True,  "sub_dk": False},
    # Groups B-D — single-candidate pools
    {"case_id": "s_inv04", "model_rel": STRIPE_MODEL, "true_eid": "e_join_charge",
     "div_cols": _GROUP_B_COLS, "diff_id": "s_inv04", "amb": False, "sub_dk": False},
    {"case_id": "s_inv05", "model_rel": STRIPE_MODEL, "true_eid": "e_join_sub",
     "div_cols": _GROUP_C_COLS, "diff_id": "s_inv05", "amb": False, "sub_dk": False},
    {"case_id": "s_inv06", "model_rel": STRIPE_MODEL, "true_eid": "e_join_cust",
     "div_cols": _GROUP_D_COLS, "diff_id": "s_inv06", "amb": False, "sub_dk": False},
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
    SELECT candidates: search AS <alias> in changed lines only.
    JOIN candidates  : search joined_table name in full hunk.
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
    """10-feature base vector."""
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
    """11-feature vector: base + diff_kind_match."""
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
    """12-feature vector: Phase 2b + alias_in_hunk."""
    base       = _features_2b(cand, diverged_cols, row_count_changed,
                               model_rel, diff_kind, freq_ctx)
    alias_feat = _alias_in_hunk(cand, hunk)
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
    print("alias_in_hunk pre-flight "
          "(expected: true candidate UNIQUE for Group A sub_dk cases):")
    for case in EPISODE_CASES:
        case_id  = case["case_id"]
        hunk     = STRIPE_DIFFS[case["diff_id"]]
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
        raise RuntimeError("Diff validation failed — check hunk construction.")
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
    print(f"Phase 3 transfer -- fivetran/dbt_stripe (CHILD-AGGREGATE-JOIN)")
    print(f"GREEN overall  : learned_3 > static + {DELTA} AND > freq + {DELTA}")
    print(f"GREEN sub_dk   : delta_3_vs_2b(sub_dk) >= {DELTA}")
    print(f"Sub-dk subset  : s_inv01 + s_inv02  (both-agg, diff_kind_match tied)")
    print(f"Attribution    : diff_kind fires if d_2b_vs_static >= {DELTA}")
    print(f"               : alias fires if d_sub_dk >= {DELTA}")
    print(f"{'='*72}")

    for ep_idx, (rnd, case) in enumerate(all_episodes):
        case_id   = case["case_id"]
        model_rel = case["model_rel"]
        true_eid  = case["true_eid"]
        div_cols  = case["div_cols"]
        hunk      = STRIPE_DIFFS[case["diff_id"]]

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

        # Collect training features
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
            d_2b_s_cp = mrr_2b_cp - mrr_s_cp

            if d_sub_cp >= DELTA:
                cp_tag = "GREEN_alias"
            elif d_sub_cp > 0:
                cp_tag = "YELLOW_alias"
            else:
                cp_tag = "RED_alias"

            dk_tag = "dk_fires" if d_2b_s_cp >= DELTA else "dk_flat"

            print(f"\n--- Checkpoint ep {ep_num} (round {rnd}) ---")
            print(f"  {'Method':<14} {'MRR_full':>9}   {'MRR_sub_dk':>10}")
            print(f"  {'-'*38}")
            for label, rrs in [("static",     rr_static),
                                ("frequency",  rr_freq),
                                ("learned_2b", rrs_2b),
                                ("learned_3",  rrs_3)]:
                sub   = [x for x, d in zip(rrs[:ep_num], ep_detail[:ep_num])
                         if d["sub_dk"]]
                m_all = float(np.mean(rrs[:ep_num]))
                m_sub = float(np.mean(sub)) if sub else float("nan")
                print(f"  {label:<14} {m_all:>9.3f}   {m_sub:>10.3f}")
            print(f"  d_2b_vs_static: {d_2b_s_cp:+.3f} ({dk_tag})"
                  f"  d_sub_dk: {d_sub_cp:+.3f} -> {cp_tag}")

    # ---- Final verdict ----
    mrr_s_f  = float(np.mean(rr_static))
    mrr_f_f  = float(np.mean(rr_freq))
    mrr_2b_f = float(np.mean(rrs_2b))
    mrr_3_f  = float(np.mean(rrs_3))

    d_2b_vs_static = mrr_2b_f - mrr_s_f
    d_3_vs_static  = mrr_3_f  - mrr_s_f
    d_3_vs_freq    = mrr_3_f  - mrr_f_f
    d_full         = mrr_3_f  - mrr_2b_f

    sub_2b_all = [x for x, d in zip(rrs_2b, ep_detail) if d["sub_dk"]]
    sub_3_all  = [x for x, d in zip(rrs_3,  ep_detail) if d["sub_dk"]]
    mrr_sub_2b = float(np.mean(sub_2b_all)) if sub_2b_all else float("nan")
    mrr_sub_3  = float(np.mean(sub_3_all))  if sub_3_all  else float("nan")
    d_subset   = mrr_sub_3 - mrr_sub_2b

    # Overall verdict
    if d_3_vs_static >= DELTA and d_3_vs_freq >= DELTA:
        overall_verdict = "GREEN"
    elif d_3_vs_static >= DELTA:
        overall_verdict = "YELLOW"
    else:
        overall_verdict = "RED"

    # diff_kind attribution
    dk_fires = d_2b_vs_static >= DELTA

    # alias attribution (sub-dk)
    if d_subset >= DELTA:
        alias_verdict = "GREEN"
    elif d_subset > 0:
        alias_verdict = "YELLOW"
    else:
        alias_verdict = "RED"

    # Combined attribution
    if dk_fires and alias_verdict == "GREEN":
        attribution = "BOTH_FIRE"
    elif dk_fires:
        attribution = "ONLY_DIFF_KIND"
    elif alias_verdict == "GREEN":
        attribution = "ONLY_ALIAS"
    else:
        attribution = "NEITHER"

    print(f"\n{'='*72}")
    print(f"PHASE 3 TRANSFER VERDICT: {overall_verdict}")
    print(f"  Project                   : fivetran/dbt_stripe")
    print(f"  Structural pattern        : CHILD-AGGREGATE-JOIN")
    print(f"  Feature added             : alias_in_hunk")
    print(f"  MRR static                : {mrr_s_f:.3f}")
    print(f"  MRR frequency             : {mrr_f_f:.3f}")
    print(f"  MRR learned_2b            : {mrr_2b_f:.3f}")
    print(f"  MRR learned_3             : {mrr_3_f:.3f}")
    print(f"  d_2b_vs_static            : {d_2b_vs_static:+.3f}  "
          f"{'(diff_kind FIRES)' if dk_fires else '(diff_kind flat)'}")
    print(f"  d_3_vs_static             : {d_3_vs_static:+.3f}")
    print(f"  d_3_vs_freq               : {d_3_vs_freq:+.3f}")
    print(f"  MRR_sub_dk learned_2b     : {mrr_sub_2b:.3f}  (s_inv01 + s_inv02)")
    print(f"  MRR_sub_dk learned_3      : {mrr_sub_3:.3f}")
    print(f"  d_sub_dk (alias verdict)  : {d_subset:+.3f}  -> {alias_verdict}")
    print(f"  Attribution               : {attribution}")
    print(f"{'='*72}")

    # Group A breakdown
    print(f"\nGroup A (invoice_line_item, n_cands=3):")
    for case_id in ("s_inv01", "s_inv02", "s_inv03"):
        eps    = [d for d in ep_detail if d["case_id"] == case_id]
        avg_s  = float(np.mean([e["rr_s"]  for e in eps]))
        avg_f  = float(np.mean([e["rr_f"]  for e in eps]))
        avg_2b = float(np.mean([e["rr_2b"] for e in eps]))
        avg_3  = float(np.mean([e["rr_3"]  for e in eps]))
        true_eid = next(c["true_eid"] for c in EPISODE_CASES
                        if c["case_id"] == case_id)
        dk = eps[0]["diff_kind"] if eps else "?"
        sdk = " [sub_dk]" if any(e["sub_dk"] for e in eps) else ""
        print(f"  {case_id}{sdk} (true={true_eid}, diff={dk}): "
              f"static={avg_s:.3f}  freq={avg_f:.3f}  "
              f"2b={avg_2b:.3f}  3={avg_3:.3f}")

    # Groups B-D breakdown
    print(f"\nGroups B-D (single-candidate pools):")
    for case_id in ("s_inv04", "s_inv05", "s_inv06"):
        eps    = [d for d in ep_detail if d["case_id"] == case_id]
        avg_3  = float(np.mean([e["rr_3"]  for e in eps]))
        true_eid = next(c["true_eid"] for c in EPISODE_CASES
                        if c["case_id"] == case_id)
        dk = eps[0]["diff_kind"] if eps else "?"
        print(f"  {case_id} (true={true_eid}, diff={dk}): "
              f"rr_3={avg_3:.3f} (trivially correct)")

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
    hdr = (f"{'ep':>4} {'rnd':>3} {'case_id':<10} {'dk':<8} "
           f"{'amb':<4} {'sdk':<4} {'nc':>3} "
           f"{'r_s':>4} {'r_f':>4} {'r_2b':>5} {'r_3':>4} "
           f"{'rr_s':>6} {'rr_f':>6} {'rr_2b':>7} {'rr_3':>6}")
    print(f"  {hdr}")
    print(f"  {'-'*88}")
    for d in ep_detail:
        print(f"  {d['ep']:>4} {d['rnd']:>3}  {d['case_id']:<10} "
              f"{d['diff_kind']:<8} "
              f"{'Y' if d['amb'] else 'N':<4} {'Y' if d['sub_dk'] else 'N':<4} "
              f"{d['n_cands']:>3} "
              f"{d['r_s']:>4} {d['r_f']:>4} {d['r_2b']:>5} {d['r_3']:>4} "
              f"{d['rr_s']:>6.3f} {d['rr_f']:>6.3f} "
              f"{d['rr_2b']:>7.3f} {d['rr_3']:>6.3f}")

    # Save results
    result = {
        "project": "fivetran/dbt_stripe",
        "structural_pattern": "CHILD-AGGREGATE-JOIN",
        "phase": 3,
        "feature_added": "alias_in_hunk",
        "n_cases": N_CASES, "n_rounds": N_ROUNDS, "total_episodes": total_eps,
        "mrr_static": mrr_s_f, "mrr_freq": mrr_f_f,
        "mrr_2b": mrr_2b_f, "mrr_3": mrr_3_f,
        "d_2b_vs_static": d_2b_vs_static,
        "d_3_vs_static": d_3_vs_static,
        "d_3_vs_freq": d_3_vs_freq,
        "d_3_vs_2b_full": d_full,
        "mrr_sub_dk_2b": mrr_sub_2b,
        "mrr_sub_dk_3": mrr_sub_3,
        "d_sub_dk": d_subset,
        "overall_verdict": overall_verdict,
        "alias_verdict": alias_verdict,
        "dk_fires": dk_fires,
        "attribution": attribution,
        "feature_weights_2b": (
            dict(zip(feat_names_2b, clf_2b.coef_[0].tolist())) if clf_2b else None),
        "feature_weights_3": (
            dict(zip(feat_names_3,  clf_3.coef_[0].tolist()))  if clf_3  else None),
        "episodes": ep_detail,
    }
    OUT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"\nResults saved: {OUT}")
    return result


if __name__ == "__main__":
    run_simulation()
