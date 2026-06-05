"""
OPEN-72: Shared Structure Index (SSI).
Tests whether SSI — computed from CE labels only — predicts whether a CE
feature set can produce positive ER transfer groups.

Definition:
  SSI(F) = 1 - mean(corr(f_i, y_CE)^2  for all features i)

Two feature sets, evaluated on their respective corpora:
  A. turn-derived (15-dim)   — 108 pilot episodes (turn_rows format)
  B. dimension_scores (4-dim) — 208 matrix episodes (a5/a6/a7)

Ground truth alignment results (from OPEN-71b / OPEN-71b-larger):
  A: 3 positive groups (s02-screening, s04, s05)
  B: 0 positive groups (all locked to CE outcome)

Pre-committed verdict bands:
  GREEN:  SSI(dim_scores) < SSI(turn-derived)  AND  gap >= 0.2
  YELLOW: correctly ranked but gap < 0.2
  RED:    SSI fails to rank correctly
"""

import json, glob, math, os
from collections import defaultdict

PILOT = os.path.join(os.path.dirname(__file__), "..", "pilot_matrix_results")
_NEG_SIGNALS = {"conversation_stalled", "phone_requested_too_early"}
MARGIN_THRESHOLD = 0.2   # pre-committed; do not change after seeing results

DIM_KEYS = ["answered_landlord_naturally", "phone_timing_ok",
            "safe_phone_capture", "viewing_progressed"]

_SPEAKER = {"actor": 0.0, "landlord": 0.0, "agent": 1.0}
_STATES  = ["screening","viewing_negotiation","viewing_confirmed","phone_captured","stalled"]


# ── corpus A: turn-derived (108 pilot episodes) ───────────────────────────────

def load_turn_episodes():
    eps = []
    for jf in glob.glob(os.path.join(PILOT, "**", "*.jsonl"), recursive=True):
        try:
            with open(jf) as fh:
                for line in fh:
                    ep = json.loads(line)
                    if "turn_rows" not in ep or "summary" not in ep or not ep["turn_rows"]:
                        continue
                    all_signals = {sig for tr in ep["turn_rows"]
                                   for sig in tr.get("flipped_signals", [])}
                    ep["_pc"] = "phone_captured" in all_signals
                    ep["_sk"] = ep.get("scenario_key", "unk")
                    eps.append(ep)
        except Exception:
            pass
    return eps


def turn_features(ep):
    rows = ep["turn_rows"]
    n = max(len(rows), 1)
    idx_mean  = sum(r["turn_index_0based"] for r in rows) / n / max(n-1, 1)
    spk_mean  = sum(_SPEAKER.get(r["speaker"], 0.0) for r in rows) / n
    aph_frac  = sum(1 for r in rows if r.get("agent_asked_phone")) / n
    mlen_mean = sum(min(len(r.get("message",""))/500.0, 1.0) for r in rows) / n
    state_frac = [sum(1 for r in rows if r.get("current_state","") == s) / n
                  for s in _STATES]
    actor_rows = [r for r in rows if r["speaker"] == "actor"]
    na = max(len(actor_rows), 1)
    branch_frac = [
        sum(1 for r in actor_rows if r.get("landlord_branch") == k) / na
        for k in ["branch-1-initial","branch-2-phone-shared",
                  "branch-4-default-screening","branch-5-proactive-offer"]
    ]
    ce2_frac = sum(
        1 for r in rows
        if r.get("flipped_signals") and
           any(s not in _NEG_SIGNALS for s in r["flipped_signals"])
    ) / n
    return ([idx_mean, spk_mean, aph_frac, mlen_mean]
            + state_frac + branch_frac + [ce2_frac, n / 7.0])

TURN_FEATURE_NAMES = [
    "idx_mean", "spk_mean", "aph_frac", "mlen_mean",
    "state_screening", "state_viewing_negotiation", "state_viewing_confirmed",
    "state_phone_captured", "state_stalled",
    "branch_initial", "branch_phone_shared",
    "branch_default_screening", "branch_proactive_offer",
    "ce2_frac", "n_turns_norm",
]


# ── corpus B: dimension_scores (208 matrix episodes) ─────────────────────────

DATA_DIRS_B = [
    os.path.join(PILOT, d)
    for d in ["a5_matrix", "a6_matrix", "a7_corpus_preloaded"]
]

def load_dim_episodes():
    eps = []
    for d in DATA_DIRS_B:
        jf = os.path.join(d, "trials.jsonl")
        if not os.path.exists(jf):
            continue
        with open(jf) as fh:
            for line in fh:
                ep = json.loads(line.strip())
                if not ep.get("dimension_scores"):
                    continue
                ep["_pc"] = bool(ep.get("phone_captured", False))
                ep["_sk"] = ep.get("scenario_key", "unk")
                eps.append(ep)
    return eps


def dim_features(ep):
    d = ep.get("dimension_scores", {})
    return [float(d.get(k, 0.0)) for k in DIM_KEYS]


# ── statistics ────────────────────────────────────────────────────────────────

def pearson(xs, ys):
    n = len(xs)
    if n < 2: return float("nan")
    mx = sum(xs)/n; my = sum(ys)/n
    cov = sum((x-mx)*(y-my) for x,y in zip(xs,ys))
    sx  = math.sqrt(sum((x-mx)**2 for x in xs))
    sy  = math.sqrt(sum((y-my)**2 for y in ys) + 1e-9)
    if sx < 1e-9: return float("nan")   # constant feature → undefined, not "unlocked"
    return cov / (sx * sy)


def compute_ssi(eps, feature_fn, feature_names):
    """
    Compute SSI (raw and variance-adjusted) from CE (PC) labels only.

    SSI_raw:  treats constant features (corr=nan) as 0.0 in the mean.
              Follows the literal precommit formula.
    SSI_adj:  excludes constant features (undefined Pearson) from the mean.
              Constant features carry no information; treating them as
              "unlocked" inflates SSI_raw artificially.
    Returns (ssi_raw, ssi_adj, per_feature_info).
    """
    Xs = [feature_fn(e) for e in eps]
    ys = [1.0 if e["_pc"] else 0.0 for e in eps]
    k = len(Xs[0])
    per_feature = []
    sq_corrs_raw = []
    sq_corrs_adj = []
    for i in range(k):
        col = [x[i] for x in Xs]
        c = pearson(col, ys)
        is_constant = math.isnan(c)
        sq = 0.0 if is_constant else c**2
        sq_corrs_raw.append(sq)              # raw: nan → 0.0
        if not is_constant:
            sq_corrs_adj.append(sq)          # adj: exclude constants
        per_feature.append({
            "name":         feature_names[i] if i < len(feature_names) else f"f{i}",
            "corr_with_pc": c,
            "corr_sq":      sq,
            "constant":     is_constant,
        })
    ssi_raw = 1.0 - sum(sq_corrs_raw) / len(sq_corrs_raw)
    ssi_adj = 1.0 - (sum(sq_corrs_adj) / len(sq_corrs_adj)) if sq_corrs_adj else 1.0
    return ssi_raw, ssi_adj, per_feature


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    # ── Corpus A: turn-derived ────────────────────────────────────────────────
    eps_a = load_turn_episodes()
    n_pc_a = sum(1 for e in eps_a if e["_pc"])
    ssi_a_raw, ssi_a_adj, pf_a = compute_ssi(eps_a, turn_features, TURN_FEATURE_NAMES)

    print("=== Corpus A: turn-derived features (15-dim, 108 pilot episodes) ===")
    print(f"  n={len(eps_a)}  PC-positive={n_pc_a} ({100*n_pc_a/len(eps_a):.0f}%)")
    print(f"  Known alignment result: 3 positive groups (from OPEN-71/71b)")
    print()
    print(f"  {'Feature':<30}  {'corr(f,PC)':>11}  {'corr²':>8}  {'const?':>7}  {'lock?':>6}")
    for f in sorted(pf_a, key=lambda x: (x["constant"], -abs(x["corr_with_pc"]))):
        locked = "YES" if (not f["constant"] and abs(f["corr_with_pc"]) > 0.8) else "---"
        c = f["corr_with_pc"]
        c_str = f"{c:+.4f}" if not math.isnan(c) else "    nan"
        const_str = "YES" if f["constant"] else "---"
        print(f"  {f['name']:<30}  {c_str:>11}  {f['corr_sq']:>8.4f}  {const_str:>7}  {locked:>6}")
    n_const_a = sum(1 for f in pf_a if f["constant"])
    print(f"\n  SSI_raw(turn-derived) = {ssi_a_raw:.4f}  (constant features treated as corr=0)")
    print(f"  SSI_adj(turn-derived) = {ssi_a_adj:.4f}  (constant features excluded; {n_const_a}/{len(pf_a)} excluded)")
    print()

    # ── Corpus B: dimension_scores ────────────────────────────────────────────
    eps_b = load_dim_episodes()
    n_pc_b = sum(1 for e in eps_b if e["_pc"])
    ssi_b_raw, ssi_b_adj, pf_b = compute_ssi(eps_b, dim_features, DIM_KEYS)

    print("=== Corpus B: dimension_scores (4-dim, 208 matrix episodes) ===")
    print(f"  n={len(eps_b)}  PC-positive={n_pc_b} ({100*n_pc_b/len(eps_b):.0f}%)")
    print(f"  Known alignment result: 0 positive groups (from OPEN-71b-larger)")
    print()
    print(f"  {'Feature':<30}  {'corr(f,PC)':>11}  {'corr²':>8}  {'const?':>7}  {'lock?':>6}")
    for f in sorted(pf_b, key=lambda x: (x["constant"], -abs(x["corr_with_pc"]))):
        locked = "YES" if (not f["constant"] and abs(f["corr_with_pc"]) > 0.8) else "---"
        c = f["corr_with_pc"]
        c_str = f"{c:+.4f}" if not math.isnan(c) else "    nan"
        const_str = "YES" if f["constant"] else "---"
        print(f"  {f['name']:<30}  {c_str:>11}  {f['corr_sq']:>8.4f}  {const_str:>7}  {locked:>6}")
    n_const_b = sum(1 for f in pf_b if f["constant"])
    print(f"\n  SSI_raw(dimension_scores) = {ssi_b_raw:.4f}  (constant features treated as corr=0)")
    print(f"  SSI_adj(dimension_scores) = {ssi_b_adj:.4f}  (constant features excluded; {n_const_b}/{len(pf_b)} excluded)")
    print()

    # ── Comparison ────────────────────────────────────────────────────────────
    gap_raw = ssi_a_raw - ssi_b_raw
    gap_adj = ssi_a_adj - ssi_b_adj
    ranked_raw = ssi_a_raw > ssi_b_raw
    ranked_adj = ssi_a_adj > ssi_b_adj
    stable_raw = gap_raw >= MARGIN_THRESHOLD
    stable_adj = gap_adj >= MARGIN_THRESHOLD

    mid_raw = (ssi_a_raw + ssi_b_raw) / 2.0 if ranked_raw else None
    mid_adj = (ssi_a_adj + ssi_b_adj) / 2.0 if ranked_adj else None

    print("=== SSI comparison ===")
    print(f"  {'':32}  {'SSI_raw':>8}  {'SSI_adj':>8}")
    print(f"  {'turn-derived  [3 pos groups]':<32}  {ssi_a_raw:>8.4f}  {ssi_a_adj:>8.4f}")
    print(f"  {'dim_scores    [0 pos groups]':<32}  {ssi_b_raw:>8.4f}  {ssi_b_adj:>8.4f}")
    print(f"  {'Gap':<32}  {gap_raw:>+8.4f}  {gap_adj:>+8.4f}")
    print(f"  {'Ranked correctly?':<32}  {str(ranked_raw):>8}  {str(ranked_adj):>8}")
    print(f"  {'Gap >= {:.1f} (GREEN margin)?'.format(MARGIN_THRESHOLD):<32}  {str(stable_raw):>8}  {str(stable_adj):>8}")
    print()

    n_locked_a = sum(1 for f in pf_a if not f["constant"] and abs(f["corr_with_pc"]) > 0.8)
    n_locked_b = sum(1 for f in pf_b if not f["constant"] and abs(f["corr_with_pc"]) > 0.8)
    print(f"  Locked non-constant features (|corr|>0.8): "
          f"turn-derived {n_locked_a}/{len(pf_a)-n_const_a}, "
          f"dim_scores {n_locked_b}/{len(pf_b)-n_const_b}")
    print()

    # Verdict: raw (per precommit literal formula) and adj (corrected)
    def classify(ranked, stable):
        if not ranked: return "RED"
        return "GREEN" if stable else "YELLOW"

    verdict_raw = classify(ranked_raw, stable_raw)
    verdict_adj = classify(ranked_adj, stable_adj)

    print("=== Verdicts ===")
    print(f"  SSI_raw verdict (precommit formula): {verdict_raw}")
    print(f"    Ranked={ranked_raw}, gap={gap_raw:+.4f}, stable={stable_raw}")
    print(f"  SSI_adj verdict (variance-adjusted): {verdict_adj}")
    print(f"    Ranked={ranked_adj}, gap={gap_adj:+.4f}, stable={stable_adj}")
    print()

    # Prediction check for both versions
    print("=== Prediction check ===")
    for label, mid, ssi_a_, ssi_b_ in [
        ("raw", mid_raw, ssi_a_raw, ssi_b_raw),
        ("adj", mid_adj, ssi_a_adj, ssi_b_adj),
    ]:
        if mid is None:
            print(f"  [{label}] Cannot form threshold (not ranked correctly)")
            continue
        pa = "possible" if ssi_a_ >= mid else "none"
        pb = "possible" if ssi_b_ >= mid else "none"
        ca = "CORRECT" if pa == "possible" else "WRONG"
        cb = "CORRECT" if pb == "none"     else "WRONG"
        print(f"  [{label}] T={mid:.4f}: turn-derived->{pa} ({ca}, actual=3), "
              f"dim_scores->{pb} ({cb}, actual=0)")
    print()

    out = {
        "experiment": "OPEN-72",
        "margin_threshold": MARGIN_THRESHOLD,
        "corpus_a": {
            "name": "turn-derived", "n_episodes": len(eps_a), "n_pc": n_pc_a,
            "ssi_raw": ssi_a_raw, "ssi_adj": ssi_a_adj,
            "known_positive_groups": 3,
            "per_feature": pf_a, "n_constant": n_const_a, "n_locked": n_locked_a,
        },
        "corpus_b": {
            "name": "dimension_scores", "n_episodes": len(eps_b), "n_pc": n_pc_b,
            "ssi_raw": ssi_b_raw, "ssi_adj": ssi_b_adj,
            "known_positive_groups": 0,
            "per_feature": pf_b, "n_constant": n_const_b, "n_locked": n_locked_b,
        },
        "gap_raw": gap_raw, "gap_adj": gap_adj,
        "ranked_correctly_raw": ranked_raw, "ranked_correctly_adj": ranked_adj,
        "threshold_stable_raw": stable_raw, "threshold_stable_adj": stable_adj,
        "verdict_raw": verdict_raw, "verdict_adj": verdict_adj,
    }
    outpath = os.path.join(os.path.dirname(__file__), "open72_ssi_results.json")
    with open(outpath, "w") as f:
        json.dump(out, f, indent=2)
    print(f"Results: {outpath}")
    print(f"Verdict (raw/adj): {verdict_raw} / {verdict_adj}")


if __name__ == "__main__":
    main()
