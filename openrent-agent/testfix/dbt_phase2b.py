"""
testfix/dbt_phase2b.py -- Phase 2b: add one diff-context feature family.

Phase 2a result: YELLOW (static=0.740, freq=0.821, learned=0.833).
Residual ceiling: d_c04/d_c05 oscillation (shared ctx_key); d001 at rank 2.

Phase 2b adds: diff_kind_match -- per candidate, 1 if episode diff type
(agg/join/other) matches this candidate's expression type.

diff_kind is computed by diff_parser.classify_diff_kind(hunk) -- a real SQL
diff parser, not a hardcoded lookup.  For this simulation, diff hunks are
taken from diff_parser.JAFFLE_DIFFS (synthetic diffs constructed from the
actual model SQL, validated to produce correct classifications).

In a live repair loop: the hunk comes from `git diff` at mutation time.
The parser logic is the same either way.

Precommit: testfix/PHASE2B-precommit.md
Registered prediction: YELLOW (borderline GREEN possible).
"""

import json
import random
import pathlib
from typing import Dict, List, Tuple

import numpy as np
from diff_parser import classify_diff_kind, JAFFLE_DIFFS

HERE  = pathlib.Path(__file__).resolve().parent
AUDIT = HERE / "dbt_audit_results.json"
OUT   = HERE / "dbt_phase2b_results.json"

DELTA       = 0.05
N_ROUNDS    = 4
CHECKPOINTS = [10, 20, 30, 44]
ROUND_SEEDS = [42, 43, 44, 45]

# ---- expression candidates ----
EXPRESSION_CANDIDATES = {
    "models/customers.sql": [
        {"expr_id": "e_co_join",   "feeds_cols": frozenset(["first_order","most_recent_order","number_of_orders"]),
         "is_join": True,  "is_agg": False, "line": 62},
        {"expr_id": "e_cp_join",   "feeds_cols": frozenset(["customer_lifetime_value"]),
         "is_join": True,  "is_agg": False, "line": 65},
        {"expr_id": "e_inner_join","feeds_cols": frozenset(["customer_lifetime_value"]),
         "is_join": True,  "is_agg": False, "line": 42},
        {"expr_id": "e_min",       "feeds_cols": frozenset(["first_order"]),
         "is_join": False, "is_agg": True,  "line": 24},
        {"expr_id": "e_max",       "feeds_cols": frozenset(["most_recent_order"]),
         "is_join": False, "is_agg": True,  "line": 25},
        {"expr_id": "e_count",     "feeds_cols": frozenset(["number_of_orders"]),
         "is_join": False, "is_agg": True,  "line": 26},
        {"expr_id": "e_sum",       "feeds_cols": frozenset(["customer_lifetime_value"]),
         "is_join": False, "is_agg": True,  "line": 37},
    ],
    "models/orders.sql": [
        {"expr_id": "e_join",  "feeds_cols": frozenset(["credit_card_amount","coupon_amount",
                                                         "bank_transfer_amount","gift_card_amount","amount"]),
         "is_join": True,  "is_agg": False, "line": 52},
        {"expr_id": "e_case",  "feeds_cols": frozenset(["credit_card_amount","coupon_amount",
                                                         "bank_transfer_amount","gift_card_amount"]),
         "is_join": False, "is_agg": True,  "line": 21},
        {"expr_id": "e_total", "feeds_cols": frozenset(["amount"]),
         "is_join": False, "is_agg": True,  "line": 24},
    ],
    "models/staging/stg_payments.sql": [
        {"expr_id": "e_div", "feeds_cols": frozenset(["amount"]),
         "is_join": False, "is_agg": False, "line": 19},
    ],
}

_MODEL_N_COLS = {
    "models/customers.sql": 7,
    "models/orders.sql": 9,
    "models/staging/stg_payments.sql": 1,
}

# Phase 2b: diff_kind per episode, now computed by the real SQL diff parser.
# Hunk source: JAFFLE_DIFFS[case_id] (synthetic diffs from actual model SQL).
# In a live loop: hunk = subprocess.check_output(["git", "diff", mutation_commit])
# Parser is validated: diff_parser.validate() → 11/11 correct for jaffle_shop.
def _get_diff_kind(case_id: str, hunk: str = None) -> str:
    """Return diff_kind for this episode. Uses provided hunk or falls back to JAFFLE_DIFFS."""
    h = hunk if hunk is not None else JAFFLE_DIFFS.get(case_id, "")
    return classify_diff_kind(h) if h else "unknown"


# ---- feature extraction ----

def _base_features(cand: dict, diverged_cols: List[str],
                   row_count_changed: bool, model_rel: str,
                   freq_ctx: Dict = None) -> List[float]:
    """10-feature vector (Phase 2a): 9 structural + hist_freq."""
    div_set   = frozenset(diverged_cols)
    feeds     = cand["feeds_cols"]
    n_div     = len(div_set)
    n_total   = _MODEL_N_COLS.get(model_rel, max(n_div, 1))
    max_feeds = max(len(e["feeds_cols"]) for e in EXPRESSION_CANDIDATES.get(model_rel, [cand]))

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
        nc, ns = freq_ctx.get(ctx_key, {}).get(cand["expr_id"], (0, 0))
        hist = nc / ns if ns > 0 else 0.5
    else:
        hist = 0.5

    return [exact, superset, overlap, is_join, is_agg,
            feeds_norm, n_div_norm, row_ct, single, hist]


def _features_2b(cand: dict, diverged_cols: List[str],
                 row_count_changed: bool, model_rel: str,
                 case_id: str, freq_ctx: Dict = None,
                 diff_hunk: str = None) -> List[float]:
    """11-feature vector (Phase 2b): base + diff_kind_match.

    diff_kind_match = 1 if the diff type (parsed from hunk) matches this
    candidate's expression type (agg/join).  0 otherwise.
    """
    base      = _base_features(cand, diverged_cols, row_count_changed, model_rel, freq_ctx)
    diff_kind = _get_diff_kind(case_id, diff_hunk)
    diff_kind_match = float(
        (diff_kind == "agg"  and cand["is_agg"])
        or (diff_kind == "join" and cand["is_join"])
    )
    return base + [diff_kind_match]


FEATURE_NAMES_2A = ["exact_match", "superset_match", "any_overlap",
                    "is_join", "is_agg", "feeds_norm", "n_div_norm",
                    "row_count_changed", "single_col", "hist_freq"]

FEATURE_NAMES_2B = FEATURE_NAMES_2A + ["diff_kind_match"]


# ---- ranking ----

def _rank_static(cands: List[dict], diverged_cols: List[str]) -> List[str]:
    div_set = frozenset(diverged_cols)
    def key(c):
        feeds = c["feeds_cols"]
        exact    = feeds == div_set
        superset = div_set <= feeds
        overlap  = len(feeds & div_set) > 0
        tier = 0 if exact else (1 if superset else (2 if overlap else 3))
        return (tier, -int(c["is_agg"]), c["line"])
    return [c["expr_id"] for c in sorted(cands, key=key)]


def _rank_frequency(cands: List[dict], freq_ctx: Dict,
                    diverged_cols: List[str], model_rel: str,
                    static_order: List[str]) -> List[str]:
    div_set    = frozenset(diverged_cols)
    ctx_key    = (model_rel, div_set)
    ctx_counts = freq_ctx.get(ctx_key, {})
    static_pos = {eid: i for i, eid in enumerate(static_order)}

    def score(c):
        feeds   = c["feeds_cols"]
        exact   = feeds == div_set
        sup     = div_set <= feeds
        overlap = len(feeds & div_set) > 0
        tier    = 0 if exact else (1 if sup else (2 if overlap else 3))
        if tier == 3:
            return (3, 0, 0.0, static_pos.get(c["expr_id"], 99))
        nc, ns = ctx_counts.get(c["expr_id"], (0, 0))
        p = nc / ns if ns > 0 else 0.5
        return (tier, 0, -p, static_pos.get(c["expr_id"], 99))

    return [c["expr_id"] for c in sorted(cands, key=score)]


def _rank_learned(cands: List[dict], feat_fn, clf, static_order: List[str]) -> List[str]:
    """Rank by logistic regression. feat_fn(cand) -> feature vector."""
    if clf is None:
        return static_order[:]
    static_pos = {eid: i for i, eid in enumerate(static_order)}
    scores = []
    for c in cands:
        feat = feat_fn(c)
        prob = clf.predict_proba([feat])[0][1]
        scores.append((c["expr_id"], prob, static_pos.get(c["expr_id"], 99)))
    scores.sort(key=lambda x: (-x[1], x[2]))
    return [s[0] for s in scores]


# ---- classifier ----

def _fit(X: List[List[float]], y: List[int]):
    if not X or sum(y) < 1 or sum(1 - yi for yi in y) < 1:
        return None
    try:
        from sklearn.linear_model import LogisticRegression
        clf = LogisticRegression(C=1.0, max_iter=200, solver="lbfgs")
        clf.fit(np.array(X), np.array(y))
        return clf
    except Exception:
        return None


# ---- MRR ----

def _mrr_at(records, up_to: int) -> float:
    recs = [r for r in records if r["episode_idx"] <= up_to]
    return sum(r["rr"] for r in recs) / len(recs) if recs else 0.0


# ---- main ----

def main():
    with open(AUDIT, encoding="utf-8") as f:
        audit = json.load(f)

    detectable = [r for r in audit["results"] if r["stage"] == "detected"]
    n_det = len(detectable)
    print(f"Detectable mutations: {n_det}")

    for r in detectable:
        fd = r["l1_first_divergent"]
        r["_div_cols"]  = r["l2_diverged_cols"].get(fd, [])
        r["_row_ct"]    = r["l2_row_count_changed"].get(fd, False)
        r["_model_rel"] = next(
            (k for k, v in {
                "models/customers.sql":            "customers",
                "models/orders.sql":               "orders",
                "models/staging/stg_payments.sql": "stg_payments",
            }.items() if v == fd), None)
        r["_ambiguous"] = not r["l2_unique_exact"]

    episodes = []
    for rnd, seed in enumerate(ROUND_SEEDS):
        rng = random.Random(seed)
        order = list(range(n_det))
        rng.shuffle(order)
        for idx in order:
            episodes.append({"round": rnd + 1, "mutation": detectable[idx]})
    print(f"Total episodes: {len(episodes)}")

    # Shared state
    freq_ctx: Dict[Tuple, Dict[str, Tuple[int, int]]] = {}
    # Separate training streams for 2a and 2b learned models
    X_2a: List[List[float]] = [];  y_2a: List[int] = [];  clf_2a = None
    X_2b: List[List[float]] = [];  y_2b: List[int] = [];  clf_2b = None

    rec_static  = []
    rec_freq    = []
    rec_2a      = []
    rec_2b      = []

    sep = "=" * 72
    print(f"\n{sep}")
    print("Phase 2b — diff-context feature: diff_kind_match")
    print(f"Registered prediction: YELLOW")
    print(sep)

    for ep_idx, ep in enumerate(episodes):
        mut      = ep["mutation"]
        model_rel = mut["_model_rel"]
        cands    = EXPRESSION_CANDIDATES.get(model_rel, [])
        div_cols = mut["_div_cols"]
        row_ct   = mut["_row_ct"]
        true_eid = mut["true_expr_id"]
        case_id  = mut["case_id"]

        if not cands or not div_cols:
            continue

        static_order = _rank_static(cands, div_cols)

        # Feature callables for this episode
        feat_2a = lambda c, _dc=div_cols, _rc=row_ct, _mr=model_rel: \
            _base_features(c, _dc, _rc, _mr, freq_ctx)
        feat_2b = lambda c, _dc=div_cols, _rc=row_ct, _mr=model_rel, _ci=case_id: \
            _features_2b(c, _dc, _rc, _mr, _ci, freq_ctx)

        freq_order = _rank_frequency(cands, freq_ctx, div_cols, model_rel, static_order)
        order_2a   = _rank_learned(cands, feat_2a, clf_2a, static_order)
        order_2b   = _rank_learned(cands, feat_2b, clf_2b, static_order)

        def rank_of(order, eid):
            try:    return order.index(eid) + 1
            except: return len(order) + 1

        r_s  = rank_of(static_order, true_eid)
        r_f  = rank_of(freq_order,   true_eid)
        r_2a = rank_of(order_2a,     true_eid)
        r_2b = rank_of(order_2b,     true_eid)

        kw = {"episode_idx": ep_idx+1, "ambiguous": mut["_ambiguous"], "case_id": case_id}
        rec_static.append({**kw, "rr": 1/r_s})
        rec_freq.append(  {**kw, "rr": 1/r_f})
        rec_2a.append(    {**kw, "rr": 1/r_2a})
        rec_2b.append(    {**kw, "rr": 1/r_2b})

        # Update frequency
        div_set = frozenset(div_cols)
        ctx_key = (model_rel, div_set)
        if ctx_key not in freq_ctx:
            freq_ctx[ctx_key] = {}
        n_total = _MODEL_N_COLS.get(model_rel, 1)
        all_diverged = len(div_set) >= n_total
        for c in cands:
            if len(c["feeds_cols"] & div_set) > 0 or all_diverged:
                eid = c["expr_id"]
                nc, ns = freq_ctx[ctx_key].get(eid, (0, 0))
                freq_ctx[ctx_key][eid] = (nc + int(eid == true_eid), ns + 1)

        # Update 2a training (after freq update so hist_freq is current)
        for c in cands:
            X_2a.append(_base_features(c, div_cols, row_ct, model_rel, freq_ctx))
            y_2a.append(int(c["expr_id"] == true_eid))
        clf_2a = _fit(X_2a, y_2a)

        # Update 2b training
        for c in cands:
            X_2b.append(_features_2b(c, div_cols, row_ct, model_rel, case_id, freq_ctx))
            y_2b.append(int(c["expr_id"] == true_eid))
        clf_2b = _fit(X_2b, y_2b)

        # Checkpoint
        if (ep_idx + 1) in CHECKPOINTS:
            t = ep_idx + 1
            ms = _mrr_at(rec_static, t);  mf = _mrr_at(rec_freq, t)
            m2a = _mrr_at(rec_2a, t);     m2b = _mrr_at(rec_2b, t)
            ms_u = _mrr_at([r for r in rec_static if not r["ambiguous"]], t)
            mf_u = _mrr_at([r for r in rec_freq   if not r["ambiguous"]], t)
            m2a_u= _mrr_at([r for r in rec_2a     if not r["ambiguous"]], t)
            m2b_u= _mrr_at([r for r in rec_2b     if not r["ambiguous"]], t)
            ms_a = _mrr_at([r for r in rec_static if     r["ambiguous"]], t)
            mf_a = _mrr_at([r for r in rec_freq   if     r["ambiguous"]], t)
            m2a_a= _mrr_at([r for r in rec_2a     if     r["ambiguous"]], t)
            m2b_a= _mrr_at([r for r in rec_2b     if     r["ambiguous"]], t)

            band_2b = ("GREEN"  if m2b - ms > DELTA and m2b - mf > DELTA else
                       "YELLOW" if m2b - ms > DELTA else "RED")

            print(f"\n--- Checkpoint: episode {t} ---")
            print(f"  {'Method':<14}  {'MRR':>6}  {'MRR_uniq':>9}  {'MRR_amb':>8}")
            print(f"  {'-'*44}")
            print(f"  {'static':<14}  {ms:>6.3f}  {ms_u:>9.3f}  {ms_a:>8.3f}")
            print(f"  {'frequency':<14}  {mf:>6.3f}  {mf_u:>9.3f}  {mf_a:>8.3f}")
            print(f"  {'learned_2a':<14}  {m2a:>6.3f}  {m2a_u:>9.3f}  {m2a_a:>8.3f}")
            print(f"  {'learned_2b':<14}  {m2b:>6.3f}  {m2b_u:>9.3f}  {m2b_a:>8.3f}")
            print(f"  2b: d_vs_static={m2b-ms:+.3f}  d_vs_freq={m2b-mf:+.3f}  "
                  f"d_vs_2a={m2b-m2a:+.3f}  -> {band_2b}")

    # Final verdict
    final = CHECKPOINTS[-1]
    ms  = _mrr_at(rec_static, final);  mf  = _mrr_at(rec_freq,   final)
    m2a = _mrr_at(rec_2a,    final);   m2b = _mrr_at(rec_2b,     final)

    band_2b = ("GREEN"  if m2b - ms > DELTA and m2b - mf > DELTA else
               "YELLOW" if m2b - ms > DELTA else "RED")

    interp = {
        "GREEN":  "Diff-context encodes reusable signal beyond caching",
        "YELLOW": "Diff-context helps but only reaches caching-level performance",
        "RED":    "Diff-context does not help; ambiguity remains",
    }[band_2b]

    print(f"\n{sep}")
    print(f"PHASE 2B VERDICT: {band_2b}")
    print(f"  MRR static    : {ms:.3f}")
    print(f"  MRR frequency : {mf:.3f}")
    print(f"  MRR learned_2a: {m2a:.3f}  (Phase 2a baseline)")
    print(f"  MRR learned_2b: {m2b:.3f}  (Phase 2b with diff_kind_match)")
    print(f"  delta_2b_vs_static : {m2b-ms:+.3f}  (threshold: >{DELTA})")
    print(f"  delta_2b_vs_freq   : {m2b-mf:+.3f}  (threshold: >{DELTA} for GREEN)")
    print(f"  delta_2b_vs_2a     : {m2b-m2a:+.3f}")
    print(f"  Interpretation     : {interp}")
    print(f"  Registered pred    : YELLOW")
    print(sep)

    # Per-episode detail
    print("\nPer-episode detail:")
    print(f"  {'ep':>3}  {'rnd':>3}  {'case_id':<10}  {'amb':>3}  "
          f"{'r_s':>4}  {'r_f':>4}  {'r_2a':>5}  {'r_2b':>5}  "
          f"{'rr_s':>5}  {'rr_f':>5}  {'rr_2a':>6}  {'rr_2b':>6}")
    print("  " + "-" * 70)
    for i, ep in enumerate(episodes):
        if i >= len(rec_static):
            break
        rs = rec_static[i]; rf = rec_freq[i]; r2a = rec_2a[i]; r2b = rec_2b[i]
        amb = "Y" if rs["ambiguous"] else "N"
        def ri(r): return round(1/r["rr"]) if r["rr"] > 0 else "?"
        print(f"  {i+1:>3}  {ep['round']:>3}  {rs['case_id']:<10}  {amb:>3}  "
              f"{str(ri(rs)):>4}  {str(ri(rf)):>4}  {str(ri(r2a)):>5}  {str(ri(r2b)):>5}  "
              f"{rs['rr']:>5.3f}  {rf['rr']:>5.3f}  {r2a['rr']:>6.3f}  {r2b['rr']:>6.3f}")

    # Feature weights
    for label, clf, names in [("2a", clf_2a, FEATURE_NAMES_2A),
                               ("2b", clf_2b, FEATURE_NAMES_2B)]:
        if clf is not None:
            print(f"\nFeature weights (learned_{label}):")
            for name, w in sorted(zip(names, clf.coef_[0]), key=lambda x: -abs(x[1])):
                print(f"  {name:<22}: {w:+.3f}")

    # Save
    out_data = {
        "n_episodes": len(episodes),
        "delta_threshold": DELTA,
        "final": {
            "mrr_static":     round(ms,  4),
            "mrr_frequency":  round(mf,  4),
            "mrr_learned_2a": round(m2a, 4),
            "mrr_learned_2b": round(m2b, 4),
            "delta_2b_vs_static": round(m2b - ms,  4),
            "delta_2b_vs_freq":   round(m2b - mf,  4),
            "delta_2b_vs_2a":     round(m2b - m2a, 4),
            "verdict_2b": band_2b,
        },
        "feature_weights_2b": (
            {n: round(float(w), 4) for n, w in zip(FEATURE_NAMES_2B, clf_2b.coef_[0])}
            if clf_2b is not None else None
        ),
        "checkpoints": {},
    }
    for cp in CHECKPOINTS:
        out_data["checkpoints"][str(cp)] = {
            "mrr_static":     round(_mrr_at(rec_static, cp), 4),
            "mrr_frequency":  round(_mrr_at(rec_freq,   cp), 4),
            "mrr_learned_2a": round(_mrr_at(rec_2a,     cp), 4),
            "mrr_learned_2b": round(_mrr_at(rec_2b,     cp), 4),
        }
    OUT.write_text(json.dumps(out_data, indent=2), encoding="utf-8")
    print(f"\nResults saved: {OUT}")


if __name__ == "__main__":
    main()
