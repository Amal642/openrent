"""
OPEN-71: CE-signal alignment gating.
Question: Does per-group CE<->ER sign-check prevent the negative transfer from OPEN-70?

CE2 oracle (training label): phone_captured (episode-level)
ER oracle  (eval label):     viewing_confirmed_ever

Procedure (exactly as precommitted):
  1. Compute per-group Pearson correlation between CE2 episode score and VC label.
     Classify: positive (corr > +0.05), neutral (|corr| <= 0.05), negative (corr < -0.05).
  2. Ungated model: LR trained on PC labels, score all episodes, MRR vs VC.
  3. Gated model: positive-aligned groups use CE2 score; neutral/negative groups get 0.5.
  4. Static baseline: rank by -seed within group.
  5. 8 seeds, three-way comparison.

Pre-committed verdict bands:
  GREEN:  gated delta vs static >= +0.05
  YELLOW: gated delta vs static in (0, +0.05)  -- harm removed, no lift
  RED:    gated delta vs static <= 0            -- gating fails to prevent harm

Correlation thresholds are fixed: +/-0.05 as precommitted. Do not adjust.
"""

import json, glob, math, os, random
from collections import defaultdict

PILOT = os.path.join(os.path.dirname(__file__), "..", "pilot_matrix_results")
_NEG_SIGNALS = {"conversation_stalled", "phone_requested_too_early"}

SEEDS = [71, 72, 73, 74, 75, 76, 77, 78]
DELTA_THRESHOLD = 0.05
CORR_POS_THRESH  =  0.05   # precommitted; do not change after seeing results
CORR_NEG_THRESH  = -0.05   # precommitted; do not change after seeing results
NEUTRAL_SCORE    = 0.5     # gated neutral/negative groups ranked by this constant


# ── data ─────────────────────────────────────────────────────────────────────

def load_episodes():
    eps = []
    for jf in glob.glob(os.path.join(PILOT, "**", "*.jsonl"), recursive=True):
        try:
            with open(jf) as fh:
                for line in fh:
                    ep = json.loads(line)
                    if "turn_rows" not in ep or "summary" not in ep or not ep["turn_rows"]:
                        continue
                    s = ep["summary"]
                    all_signals = {sig for tr in ep["turn_rows"] for sig in tr.get("flipped_signals", [])}
                    ep["_pc"]   = "phone_captured" in all_signals
                    ep["_vc"]   = bool(s.get("viewing_confirmed_ever", s.get("final_state","") == "viewing_confirmed"))
                    ep["_sk"]   = ep.get("scenario_key", "unk")
                    ep["_seed"] = ep.get("seed", 0)
                    eps.append(ep)
        except Exception:
            pass
    return eps


# ── features (identical to OPEN-70) ──────────────────────────────────────────

_SPEAKER = {"actor": 0.0, "landlord": 0.0, "agent": 1.0}
_STATES  = ["screening","viewing_negotiation","viewing_confirmed","phone_captured","stalled"]
_NEG_SIG = _NEG_SIGNALS

def episode_features(ep):
    rows = ep["turn_rows"]
    n = max(len(rows), 1)
    idx_mean  = sum(r["turn_index_0based"] for r in rows) / n / max(n-1, 1)
    spk_mean  = sum(_SPEAKER.get(r["speaker"], 0.0) for r in rows) / n
    aph_frac  = sum(1 for r in rows if r.get("agent_asked_phone")) / n
    mlen_mean = sum(min(len(r.get("message",""))/500.0, 1.0) for r in rows) / n
    state_frac = [sum(1 for r in rows if r.get("current_state","") == s) / n for s in _STATES]
    actor_rows = [r for r in rows if r["speaker"] == "actor"]
    na = max(len(actor_rows), 1)
    branch_frac = [
        sum(1 for r in actor_rows if r.get("landlord_branch") == k) / na
        for k in ["branch-1-initial","branch-2-phone-shared","branch-4-default-screening","branch-5-proactive-offer"]
    ]
    ce2_frac = sum(
        1 for r in rows
        if r.get("flipped_signals") and any(s not in _NEG_SIG for s in r["flipped_signals"])
    ) / n
    n_turns_norm = n / 7.0
    return [idx_mean, spk_mean, aph_frac, mlen_mean] + state_frac + branch_frac + [ce2_frac, n_turns_norm]


# ── logistic regression ───────────────────────────────────────────────────────

def _sigmoid(x): return 1.0 / (1.0 + math.exp(-max(-60, min(60, x))))
def _dot(w, x):  return sum(a*b for a, b in zip(w, x))

def _lr_train(Xs, ys, lr=0.05, epochs=400, l2=0.01):
    w = [0.0] * len(Xs[0]); b = 0.0
    for _ in range(epochs):
        for x, y in zip(Xs, ys):
            p = _sigmoid(_dot(w, x) + b); g = p - y
            w = [wi - lr*(g*xi + l2*wi) for wi, xi in zip(w, x)]
            b -= lr * g
    return w, b

def _predict(w, b, x): return _sigmoid(_dot(w, x) + b)


# ── Pearson correlation ───────────────────────────────────────────────────────

def pearson(xs, ys):
    n = len(xs)
    if n < 2: return 0.0
    mx = sum(xs)/n; my = sum(ys)/n
    cov  = sum((x-mx)*(y-my) for x,y in zip(xs,ys))
    sx   = math.sqrt(sum((x-mx)**2 for x in xs) + 1e-9)
    sy   = math.sqrt(sum((y-my)**2 for y in ys) + 1e-9)
    return cov / (sx * sy)


# ── MRR ──────────────────────────────────────────────────────────────────────

def mrr_groups(groups):
    rrs = []
    for eps_group in groups.values():
        ranked = sorted(eps_group, key=lambda e: -e["_score"])
        for rank, ep in enumerate(ranked, 1):
            if ep["_vc"]:
                rrs.append(1.0/rank); break
        else:
            rrs.append(0.0)
    return sum(rrs)/len(rrs) if rrs else 0.0

def valid_groups(eps):
    g = defaultdict(list)
    for ep in eps: g[ep["_sk"]].append(ep)
    return {sk: v for sk, v in g.items() if any(e["_vc"] for e in v)}


# ── per-group correlation (uses full-corpus CE2 score) ────────────────────────

def compute_group_correlations(eps, w, b):
    """Returns {sk: corr} for groups with >= 2 episodes and >= 1 positive."""
    by_sk = defaultdict(list)
    for ep in eps:
        score = _predict(w, b, episode_features(ep))
        by_sk[ep["_sk"]].append((score, 1 if ep["_vc"] else 0))
    corrs = {}
    for sk, pairs in by_sk.items():
        if len(pairs) < 2: continue
        scores = [p[0] for p in pairs]
        vcs    = [p[1] for p in pairs]
        corrs[sk] = pearson(scores, vcs)
    return corrs

def classify_group(corr):
    if corr > CORR_POS_THRESH:  return "positive"
    if corr < CORR_NEG_THRESH:  return "negative"
    return "neutral"


# ── single seed run ───────────────────────────────────────────────────────────

def run_seed(eps, seed, group_classes):
    """
    Returns (mrr_static, mrr_ungated, mrr_gated) for one seed.
    group_classes: {sk: "positive"|"neutral"|"negative"} — fixed, not recomputed per seed.
    """
    rng = random.Random(seed)

    # Train LR on PC labels (all episodes — same as OPEN-70 L2 full-corpus fit)
    Xs = [episode_features(e) for e in eps]
    ys = [1 if e["_pc"] else 0 for e in eps]
    w, b = _lr_train(Xs, ys)

    # ── ungated: score all episodes by CE2 model ──────────────────────────────
    for ep in eps:
        ep["_score"] = _predict(w, b, episode_features(ep))
    mrr_ungated = mrr_groups(valid_groups(eps))

    # ── gated: suppress CE2 for neutral/negative groups ───────────────────────
    for ep in eps:
        cls = group_classes.get(ep["_sk"], "neutral")
        if cls == "positive":
            ep["_score"] = _predict(w, b, episode_features(ep))
        else:
            ep["_score"] = NEUTRAL_SCORE
    mrr_gated = mrr_groups(valid_groups(eps))

    # ── static: rank by -seed ─────────────────────────────────────────────────
    for ep in eps:
        ep["_score"] = -ep["_seed"]
    mrr_static = mrr_groups(valid_groups(eps))

    return mrr_static, mrr_ungated, mrr_gated


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    eps = load_episodes()
    n_pc = sum(1 for e in eps if e["_pc"])
    n_vc = sum(1 for e in eps if e["_vc"])
    print(f"Episodes: {len(eps)}  PC-positive: {n_pc}  VC-positive: {n_vc}")
    print()

    # Step 1: Compute per-group correlations using full-corpus LR (seed=71 fit)
    Xs = [episode_features(e) for e in eps]
    ys = [1 if e["_pc"] else 0 for e in eps]
    w0, b0 = _lr_train(Xs, ys)
    corrs = compute_group_correlations(eps, w0, b0)
    group_classes = {sk: classify_group(c) for sk, c in corrs.items()}

    print("=== Per-group CE<->VC correlation (thresholds: pos>+0.05, neg<-0.05) ===")
    print(f"  {'Scenario':<45}  {'n':>4}  {'PC':>4}  {'VC':>4}  {'corr':>8}  {'class':>8}")
    by_sk = defaultdict(list)
    for ep in eps: by_sk[ep["_sk"]].append(ep)
    for sk in sorted(by_sk):
        g = by_sk[sk]
        pc = sum(1 for e in g if e["_pc"])
        vc = sum(1 for e in g if e["_vc"])
        c  = corrs.get(sk, float("nan"))
        cls = group_classes.get(sk, "neutral")
        print(f"  {sk:<45}  {len(g):>4}  {pc:>4}  {vc:>4}  {c:>8.4f}  {cls:>8}")
    print()
    pos_groups = [sk for sk, c in group_classes.items() if c == "positive"]
    neg_groups = [sk for sk, c in group_classes.items() if c == "negative"]
    neu_groups = [sk for sk, c in group_classes.items() if c == "neutral"]
    print(f"  Positive-aligned groups ({len(pos_groups)}): {', '.join(sorted(pos_groups)) or 'none'}")
    print(f"  Negative-aligned groups ({len(neg_groups)}): {', '.join(sorted(neg_groups)) or 'none'}")
    print(f"  Neutral groups          ({len(neu_groups)}): {', '.join(sorted(neu_groups)) or 'none'}")
    print()

    # Step 2-5: Run 8 seeds
    print("=== Seed-level results ===")
    print(f"  {'seed':>6}  {'static':>8}  {'ungated':>8}  {'gated':>8}  {'d(g-s)':>8}  {'d(g-u)':>8}")
    rows = []
    for seed in SEEDS:
        mrr_s, mrr_u, mrr_g = run_seed(eps, seed, group_classes)
        rows.append({"seed": seed, "static": mrr_s, "ungated": mrr_u, "gated": mrr_g,
                     "delta_gated_vs_static": mrr_g - mrr_s,
                     "delta_gated_vs_ungated": mrr_g - mrr_u})
        print(f"  {seed:>6}  {mrr_s:>8.4f}  {mrr_u:>8.4f}  {mrr_g:>8.4f}  {mrr_g-mrr_s:>+8.4f}  {mrr_g-mrr_u:>+8.4f}")
    print()

    # Aggregate
    mean_s = sum(r["static"]  for r in rows) / len(rows)
    mean_u = sum(r["ungated"] for r in rows) / len(rows)
    mean_g = sum(r["gated"]   for r in rows) / len(rows)
    d_g_s  = mean_g - mean_s
    d_g_u  = mean_g - mean_u

    def std(vals, mean):
        return math.sqrt(sum((v-mean)**2 for v in vals) / max(len(vals)-1, 1))

    std_s = std([r["static"]  for r in rows], mean_s)
    std_u = std([r["ungated"] for r in rows], mean_u)
    std_g = std([r["gated"]   for r in rows], mean_g)

    print("=== Aggregate (mean ± 1 std, 8 seeds) ===")
    print(f"  Static MRR   : {mean_s:.4f} ± {std_s:.4f}")
    print(f"  Ungated MRR  : {mean_u:.4f} ± {std_u:.4f}  delta_vs_static={mean_u-mean_s:+.4f}  (OPEN-70 L2)")
    print(f"  Gated MRR    : {mean_g:.4f} ± {std_g:.4f}  delta_vs_static={d_g_s:+.4f}  delta_vs_ungated={d_g_u:+.4f}")
    print()

    # L1: gating stops harm
    ungated_harms_static = mean_u < mean_s
    gated_not_below_static = mean_g >= mean_s - 0.001   # epsilon for float
    l1_verdict = "GREEN" if (ungated_harms_static and gated_not_below_static) else (
                 "PARTIAL" if gated_not_below_static else "RED")

    # L2: gated beats static by >= 0.05
    l2_verdict = "GREEN" if d_g_s >= DELTA_THRESHOLD else (
                 "YELLOW" if d_g_s > 0 else "RED")

    print("=== Verdicts ===")
    print(f"  L1 (gating stops harm): ungated<static={ungated_harms_static}, gated>=static={gated_not_below_static} -> {l1_verdict}")
    print(f"  L2 (gated beats static >=+0.05): delta={d_g_s:+.4f}, threshold=+{DELTA_THRESHOLD} -> {l2_verdict}")

    overall = (
        "GREEN"   if l1_verdict=="GREEN" and l2_verdict=="GREEN" else
        "L1_ONLY" if l1_verdict=="GREEN" else
        "RED"
    )
    print(f"  Overall: {overall}")
    print()

    out = {
        "experiment": "OPEN-71",
        "n_episodes": len(eps),
        "n_pc": n_pc,
        "n_vc": n_vc,
        "corr_thresholds": {"positive": CORR_POS_THRESH, "negative": CORR_NEG_THRESH},
        "group_correlations": {sk: {"corr": corrs[sk], "class": group_classes[sk]} for sk in sorted(corrs)},
        "positive_groups": sorted(pos_groups),
        "negative_groups": sorted(neg_groups),
        "neutral_groups":  sorted(neu_groups),
        "aggregate": {
            "mrr_static":  mean_s, "std_static":  std_s,
            "mrr_ungated": mean_u, "std_ungated": std_u,
            "mrr_gated":   mean_g, "std_gated":   std_g,
            "delta_gated_vs_static":  d_g_s,
            "delta_gated_vs_ungated": d_g_u,
        },
        "per_seed": rows,
        "l1_verdict": l1_verdict,
        "l2_verdict": l2_verdict,
        "overall_verdict": overall,
    }
    outpath = os.path.join(os.path.dirname(__file__), "open71_alignment_gating_results.json")
    with open(outpath, "w") as f: json.dump(out, f, indent=2)
    print(f"Results: {outpath}")
    print(f"Overall verdict: {overall}")

if __name__ == "__main__":
    main()
