"""
testfix/dbt_phase2a.py -- Phase 2a: accumulated-learning loop for dbt expression
localization.

Mechanism question: can self-verified repair episodes resolve structural ambiguity?
Registered prediction: YELLOW (learning > static; learning ~= success-frequency)
Precommit: testfix/PHASE2A-precommit.md

Design:
  - 4 rounds x 11 detectable mutations = 44 episodes
  - Temporal split: train on 1..t-1, evaluate on t
  - Methods: static, frequency, learned (logistic regression)
  - Features: structural only (Phase 2a)
  - Checkpoints: MRR at episodes 10, 20, 30, 44
"""

import json
import random
import pathlib
import collections
from typing import Dict, List, Tuple, Optional

import numpy as np

HERE   = pathlib.Path(__file__).resolve().parent
AUDIT  = HERE / "dbt_audit_results.json"
OUT    = HERE / "dbt_phase2a_results.json"

# Precommit delta threshold (5 pp)
DELTA  = 0.05
N_ROUNDS   = 4
CHECKPOINTS = [10, 20, 30, 44]
ROUND_SEEDS = [42, 43, 44, 45]

# ---- expression candidates (copied from dbt_audit.py) ----
EXPRESSION_CANDIDATES = {
    "models/customers.sql": [
        {"expr_id": "e_co_join",  "desc": "customer_orders join (L62)",
         "feeds_cols": frozenset(["first_order","most_recent_order","number_of_orders"]),
         "is_join": True,  "is_agg": False, "line": 62},
        {"expr_id": "e_cp_join",  "desc": "customer_payments join (L65)",
         "feeds_cols": frozenset(["customer_lifetime_value"]),
         "is_join": True,  "is_agg": False, "line": 65},
        {"expr_id": "e_inner_join","desc": "inner join in customer_payments CTE (L42)",
         "feeds_cols": frozenset(["customer_lifetime_value"]),
         "is_join": True,  "is_agg": False, "line": 42},
        {"expr_id": "e_min",  "desc": "min(order_date) (L24)",
         "feeds_cols": frozenset(["first_order"]),
         "is_join": False, "is_agg": True,  "line": 24},
        {"expr_id": "e_max",  "desc": "max(order_date) (L25)",
         "feeds_cols": frozenset(["most_recent_order"]),
         "is_join": False, "is_agg": True,  "line": 25},
        {"expr_id": "e_count","desc": "count(order_id) (L26)",
         "feeds_cols": frozenset(["number_of_orders"]),
         "is_join": False, "is_agg": True,  "line": 26},
        {"expr_id": "e_sum",  "desc": "sum(amount) in customer_payments CTE (L37)",
         "feeds_cols": frozenset(["customer_lifetime_value"]),
         "is_join": False, "is_agg": True,  "line": 37},
    ],
    "models/orders.sql": [
        {"expr_id": "e_join",  "desc": "order_payments join (L52)",
         "feeds_cols": frozenset(["credit_card_amount","coupon_amount",
                                   "bank_transfer_amount","gift_card_amount","amount"]),
         "is_join": True,  "is_agg": False, "line": 52},
        {"expr_id": "e_case",  "desc": "CASE WHEN payment_method (L21)",
         "feeds_cols": frozenset(["credit_card_amount","coupon_amount",
                                   "bank_transfer_amount","gift_card_amount"]),
         "is_join": False, "is_agg": True,  "line": 21},
        {"expr_id": "e_total", "desc": "sum(amount) as total_amount (L24)",
         "feeds_cols": frozenset(["amount"]),
         "is_join": False, "is_agg": True,  "line": 24},
    ],
    "models/staging/stg_payments.sql": [
        {"expr_id": "e_div", "desc": "amount / 100 as amount (L19)",
         "feeds_cols": frozenset(["amount"]),
         "is_join": False, "is_agg": False, "line": 19},
    ],
}

# Max columns per model (for normalisation)
_MODEL_N_COLS = {
    "models/customers.sql": 7,
    "models/orders.sql": 9,
    "models/staging/stg_payments.sql": 1,
}


# ---- feature extraction ----

def _candidate_features(cand: dict, diverged_cols: List[str],
                        row_count_changed: bool, model_rel: str,
                        freq_ctx: Dict = None) -> List[float]:
    """Per-candidate feature vector for Phase 2a.
    Structural features + historical success rate (hist_freq).
    hist_freq is 0.5 when the candidate has never been seen (neutral prior).
    """
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

    # Outcome feature: context-conditional prior success rate
    if freq_ctx is not None:
        ctx_key = (model_rel, frozenset(diverged_cols))
        nc, ns = freq_ctx.get(ctx_key, {}).get(cand["expr_id"], (0, 0))
        hist = nc / ns if ns > 0 else 0.5
    else:
        hist = 0.5

    return [exact, superset, overlap, is_join, is_agg,
            feeds_norm, n_div_norm, row_ct, single, hist]

FEATURE_NAMES = ["exact_match", "superset_match", "any_overlap",
                 "is_join", "is_agg", "feeds_norm", "n_div_norm",
                 "row_count_changed", "single_col",
                 "hist_freq"]   # outcome feature: prior success rate for this expr_id


# ---- ranking methods ----

def _rank_static(cands: List[dict], diverged_cols: List[str]) -> List[str]:
    """
    Tier ordering: exact_match > superset_match > any_overlap > no_overlap.
    Within tier: is_agg desc, then line asc.
    """
    div_set = frozenset(diverged_cols)
    def key(c):
        feeds = c["feeds_cols"]
        exact    = feeds == div_set
        superset = div_set <= feeds
        overlap  = len(feeds & div_set) > 0
        tier = 0 if exact else (1 if superset else (2 if overlap else 3))
        return (tier, -int(c["is_agg"]), c["line"])
    return [c["expr_id"] for c in sorted(cands, key=key)]


def _rank_frequency(cands: List[dict],
                    freq_ctx: Dict[Tuple, Dict[str, Tuple[int, int]]],
                    diverged_cols: List[str],
                    model_rel: str,
                    static_order: List[str]) -> List[str]:
    """
    Context-conditional frequency: P(correct | expr_id, this diverged_cols pattern).
    Key = (model_rel, frozenset(diverged_cols)).
    Cold start within context = 0.5.  No-overlap candidates rank last (tier 3 = static).
    """
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

        eid    = c["expr_id"]
        nc, ns = ctx_counts.get(eid, (0, 0))
        p      = nc / ns if ns > 0 else 0.5
        return (tier, 0, -p, static_pos.get(eid, 99))

    return [c["expr_id"] for c in sorted(cands, key=score)]


def _rank_learned(cands: List[dict], diverged_cols: List[str],
                  row_count_changed: bool, model_rel: str,
                  clf, static_order: List[str],
                  freq_ctx: Dict = None) -> List[str]:
    """
    Rank by logistic regression P(label=1). Fall back to static if no clf.
    Passes freq_ctx to feature extractor so hist_freq feature is populated.
    """
    if clf is None:
        return static_order[:]
    static_pos = {eid: i for i, eid in enumerate(static_order)}
    scores = []
    for c in cands:
        feat = _candidate_features(c, diverged_cols, row_count_changed, model_rel, freq_ctx)
        prob = clf.predict_proba([feat])[0][1]
        scores.append((c["expr_id"], prob, static_pos.get(c["expr_id"], 99)))
    scores.sort(key=lambda x: (-x[1], x[2]))
    return [s[0] for s in scores]


# ---- classifier update ----

def _fit(X: List[List[float]], y: List[int]):
    """Fit logistic regression. Returns None if not enough data."""
    if not X or sum(y) < 1 or sum(1-yi for yi in y) < 1:
        return None
    try:
        from sklearn.linear_model import LogisticRegression
        clf = LogisticRegression(C=1.0, max_iter=200, solver="lbfgs")
        clf.fit(np.array(X), np.array(y))
        return clf
    except Exception:
        return None


# ---- MRR helpers ----

def _mrr_at(records, up_to_episode: int) -> float:
    recs = [r for r in records if r["episode_idx"] <= up_to_episode]
    if not recs:
        return 0.0
    return sum(r["rr"] for r in recs) / len(recs)


# ---- main loop ----

def main():
    with open(AUDIT, encoding="utf-8") as f:
        audit = json.load(f)

    # Keep only detectable mutations
    detectable = [r for r in audit["results"] if r["stage"] == "detected"]
    n_det = len(detectable)
    print(f"Detectable mutations: {n_det}")

    # Annotate mutation class
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
        r["_ambiguous"] = not r["l2_unique_exact"]  # audit flag

    # Build episode list: N_ROUNDS rounds, shuffled within each round
    episodes = []
    for rnd, seed in enumerate(ROUND_SEEDS):
        rng = random.Random(seed)
        order = list(range(n_det))
        rng.shuffle(order)
        for idx in order:
            episodes.append({"round": rnd + 1, "mutation": detectable[idx]})
    print(f"Total episodes: {len(episodes)}")

    # State for all three methods
    freq_ctx: Dict[Tuple, Dict[str, Tuple[int, int]]] = {}  # (model_rel, div_set) -> expr_id -> (n_correct, n_seen)
    X_train: List[List[float]] = []
    y_train: List[int] = []
    clf = None

    records_static = []
    records_freq   = []
    records_learned = []

    sep = "=" * 72

    print(f"\n{sep}")
    print("Phase 2a — dbt accumulated-learning loop")
    print(f"Mechanism: can episodes resolve structural ambiguity?")
    print(f"Registered prediction: YELLOW")
    print(sep)

    for ep_idx, ep in enumerate(episodes):
        mut   = ep["mutation"]
        model_rel = mut["_model_rel"]
        cands = EXPRESSION_CANDIDATES.get(model_rel, [])
        div_cols = mut["_div_cols"]
        row_ct   = mut["_row_ct"]
        true_eid = mut["true_expr_id"]

        if not cands or not div_cols:
            continue

        static_order  = _rank_static(cands, div_cols)
        freq_order    = _rank_frequency(cands, freq_ctx, div_cols, model_rel, static_order)
        # learned uses CURRENT freq_ctx (prior to this episode's update) as hist_freq feature
        learned_order = _rank_learned(cands, div_cols, row_ct, model_rel, clf,
                                      static_order, freq_ctx)

        # Ranks (1-indexed)
        def rank_of(order, eid):
            try:
                return order.index(eid) + 1
            except ValueError:
                return len(order) + 1

        r_static  = rank_of(static_order,  true_eid)
        r_freq    = rank_of(freq_order,    true_eid)
        r_learned = rank_of(learned_order, true_eid)

        records_static.append( {"episode_idx": ep_idx+1, "rr": 1/r_static,
                                 "ambiguous": mut["_ambiguous"], "case_id": mut["case_id"]})
        records_freq.append(   {"episode_idx": ep_idx+1, "rr": 1/r_freq,
                                 "ambiguous": mut["_ambiguous"], "case_id": mut["case_id"]})
        records_learned.append({"episode_idx": ep_idx+1, "rr": 1/r_learned,
                                 "ambiguous": mut["_ambiguous"], "case_id": mut["case_id"]})

        # --- update frequency (context-conditional: key by (model_rel, div_set)) ---
        div_set = frozenset(div_cols)
        ctx_key = (model_rel, div_set)
        if ctx_key not in freq_ctx:
            freq_ctx[ctx_key] = {}
        n_total = _MODEL_N_COLS.get(model_rel, 1)
        all_diverged = (len(div_set) >= n_total)  # join explosion: all cols diverged
        for c in cands:
            has_overlap = len(c["feeds_cols"] & div_set) > 0
            if has_overlap or all_diverged:
                eid = c["expr_id"]
                n_c, n_s = freq_ctx[ctx_key].get(eid, (0, 0))
                is_true  = int(eid == true_eid)
                freq_ctx[ctx_key][eid] = (n_c + is_true, n_s + 1)

        # --- update learned (use updated freq_ctx as hist_freq for training) ---
        for c in cands:
            feat  = _candidate_features(c, div_cols, row_ct, model_rel, freq_ctx)
            label = int(c["expr_id"] == true_eid)
            X_train.append(feat)
            y_train.append(label)
        clf = _fit(X_train, y_train)

        # Checkpoint reporting
        if (ep_idx + 1) in CHECKPOINTS:
            t = ep_idx + 1
            mrr_s = _mrr_at(records_static,  t)
            mrr_f = _mrr_at(records_freq,    t)
            mrr_l = _mrr_at(records_learned, t)
            # Breakdown by mutation class
            mrr_s_uniq = _mrr_at([r for r in records_static  if not r["ambiguous"]], t)
            mrr_f_uniq = _mrr_at([r for r in records_freq    if not r["ambiguous"]], t)
            mrr_l_uniq = _mrr_at([r for r in records_learned if not r["ambiguous"]], t)
            mrr_s_amb  = _mrr_at([r for r in records_static  if     r["ambiguous"]], t)
            mrr_f_amb  = _mrr_at([r for r in records_freq    if     r["ambiguous"]], t)
            mrr_l_amb  = _mrr_at([r for r in records_learned if     r["ambiguous"]], t)

            print(f"\n--- Checkpoint: episode {t} ---")
            print(f"  {'Method':<12}  {'MRR':>6}  {'MRR_unique':>10}  {'MRR_ambig':>10}")
            print(f"  {'-'*44}")
            print(f"  {'static':<12}  {mrr_s:>6.3f}  {mrr_s_uniq:>10.3f}  {mrr_s_amb:>10.3f}")
            print(f"  {'frequency':<12}  {mrr_f:>6.3f}  {mrr_f_uniq:>10.3f}  {mrr_f_amb:>10.3f}")
            print(f"  {'learned':<12}  {mrr_l:>6.3f}  {mrr_l_uniq:>10.3f}  {mrr_l_amb:>10.3f}")

            delta_vs_static = mrr_l - mrr_s
            delta_vs_freq   = mrr_l - mrr_f
            band = ("GREEN"  if delta_vs_static > DELTA and delta_vs_freq   > DELTA else
                    "YELLOW" if delta_vs_static > DELTA and delta_vs_freq  <= DELTA else
                    "RED")
            print(f"  delta_vs_static={delta_vs_static:+.3f}  delta_vs_freq={delta_vs_freq:+.3f}  -> {band}")

    # ---- Final verdict ----
    final = CHECKPOINTS[-1]
    mrr_s = _mrr_at(records_static,  final)
    mrr_f = _mrr_at(records_freq,    final)
    mrr_l = _mrr_at(records_learned, final)

    delta_vs_static = mrr_l - mrr_s
    delta_vs_freq   = mrr_l - mrr_f

    band = ("GREEN"  if delta_vs_static > DELTA and delta_vs_freq   > DELTA else
            "YELLOW" if delta_vs_static > DELTA and delta_vs_freq  <= DELTA else
            "RED")

    interpretation = {
        "GREEN":  "Episodes encode reusable information beyond structure",
        "YELLOW": "Caching works; reuse beyond caching does not",
        "RED":    "Structure is sufficient; episodes add nothing",
    }[band]

    print(f"\n{sep}")
    print(f"PHASE 2A VERDICT: {band}")
    print(f"  MRR static   : {mrr_s:.3f}")
    print(f"  MRR frequency: {mrr_f:.3f}")
    print(f"  MRR learned  : {mrr_l:.3f}")
    print(f"  delta_vs_static: {delta_vs_static:+.3f}  (threshold: >{DELTA})")
    print(f"  delta_vs_freq  : {delta_vs_freq:+.3f}  (threshold: >{DELTA} for GREEN)")
    print(f"  Interpretation : {interpretation}")
    print(f"  Registered pred: YELLOW")
    print(sep)

    # Per-episode detail table
    print("\nPer-episode detail (learned rank):")
    print(f"  {'ep':>3}  {'rnd':>3}  {'case_id':<10}  {'amb':>3}  "
          f"{'r_s':>4}  {'r_f':>4}  {'r_l':>4}  "
          f"{'rr_s':>5}  {'rr_f':>5}  {'rr_l':>5}")
    print("  " + "-" * 60)
    for i, ep in enumerate(episodes):
        if i >= len(records_static):
            break
        rs = records_static[i]
        rf = records_freq[i]
        rl = records_learned[i]
        amb = "Y" if rs["ambiguous"] else "N"
        r_s  = round(1 / rs["rr"])  if rs["rr"]  > 0 else "?"
        r_f  = round(1 / rf["rr"])  if rf["rr"]  > 0 else "?"
        r_l  = round(1 / rl["rr"])  if rl["rr"]  > 0 else "?"
        print(f"  {i+1:>3}  {ep['round']:>3}  {rs['case_id']:<10}  {amb:>3}  "
              f"{str(r_s):>4}  {str(r_f):>4}  {str(r_l):>4}  "
              f"{rs['rr']:>5.3f}  {rf['rr']:>5.3f}  {rl['rr']:>5.3f}")

    # Feature weights at final checkpoint
    if clf is not None:
        print("\nLearned feature weights (final model):")
        for name, w in sorted(zip(FEATURE_NAMES, clf.coef_[0]),
                               key=lambda x: -abs(x[1])):
            print(f"  {name:<22}: {w:+.3f}")

    # Save results
    out_data = {
        "n_episodes": len(episodes),
        "n_rounds":   N_ROUNDS,
        "n_mutations": n_det,
        "delta_threshold": DELTA,
        "checkpoints": {},
        "final": {
            "mrr_static":    round(mrr_s, 4),
            "mrr_frequency": round(mrr_f, 4),
            "mrr_learned":   round(mrr_l, 4),
            "delta_vs_static": round(delta_vs_static, 4),
            "delta_vs_freq":   round(delta_vs_freq,   4),
            "verdict": band,
            "interpretation": interpretation,
        },
        "feature_weights": (
            {name: round(float(w), 4) for name, w in zip(FEATURE_NAMES, clf.coef_[0])}
            if clf is not None else None
        ),
        "episode_records": {
            "static":    records_static,
            "frequency": records_freq,
            "learned":   records_learned,
        },
    }
    for cp in CHECKPOINTS:
        out_data["checkpoints"][str(cp)] = {
            "mrr_static":    round(_mrr_at(records_static,  cp), 4),
            "mrr_frequency": round(_mrr_at(records_freq,    cp), 4),
            "mrr_learned":   round(_mrr_at(records_learned, cp), 4),
        }
    OUT.write_text(json.dumps(out_data, indent=2), encoding="utf-8")
    print(f"\nResults saved: {OUT}")


if __name__ == "__main__":
    main()
