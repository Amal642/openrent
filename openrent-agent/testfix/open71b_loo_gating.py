"""
OPEN-71b: LOO (leave-one-group-out) validation of alignment gating.

The gap OPEN-71 left: group classifications were computed in-sample.
Here, for each group g, the LR is trained on all *other* groups, g is scored
with that out-of-group model, and the held-out CE<->VC correlation determines
the gating decision for g.

Pre-committed verdict bands:
  GREEN:  LOO-gated delta vs static >= +0.05
  YELLOW: LOO-gated > static, delta < +0.05
  RED:    LOO-gated <= static

Correlation thresholds: +/-0.05, frozen from OPEN-71. Do not adjust.
"""

import json, glob, math, os
from collections import defaultdict

PILOT = os.path.join(os.path.dirname(__file__), "..", "pilot_matrix_results")
_NEG_SIGNALS = {"conversation_stalled", "phone_requested_too_early"}
CORR_POS =  0.05
CORR_NEG = -0.05
NEUTRAL_SCORE = 0.5
DELTA_THRESHOLD = 0.05


# ── data (identical to OPEN-70/71) ────────────────────────────────────────────

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


# ── features (identical to OPEN-71) ──────────────────────────────────────────

_SPEAKER = {"actor": 0.0, "landlord": 0.0, "agent": 1.0}
_STATES  = ["screening","viewing_negotiation","viewing_confirmed","phone_captured","stalled"]

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
        if r.get("flipped_signals") and any(s not in _NEG_SIGNALS for s in r["flipped_signals"])
    ) / n
    return [idx_mean, spk_mean, aph_frac, mlen_mean] + state_frac + branch_frac + [ce2_frac, n / 7.0]


# ── LR ────────────────────────────────────────────────────────────────────────

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


# ── Pearson ───────────────────────────────────────────────────────────────────

def pearson(xs, ys):
    n = len(xs)
    if n < 2: return float("nan")
    mx = sum(xs)/n; my = sum(ys)/n
    cov = sum((x-mx)*(y-my) for x,y in zip(xs,ys))
    sx  = math.sqrt(sum((x-mx)**2 for x in xs) + 1e-9)
    sy  = math.sqrt(sum((y-my)**2 for y in ys) + 1e-9)
    return cov / (sx * sy)

def classify(corr):
    if math.isnan(corr): return "neutral"
    if corr > CORR_POS:  return "positive"
    if corr < CORR_NEG:  return "negative"
    return "neutral"


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


# ── LOO procedure ─────────────────────────────────────────────────────────────

def run_loo(eps):
    """
    For each group g:
      - train LR on all episodes NOT in g
      - score episodes in g with that model
      - compute held-out CE<->VC corr for g -> classification
    Then apply gating using LOO classifications; compute MRR.
    Also compute full-corpus model (for ungated and OPEN-71 in-sample gating).
    Returns: mrr_static, mrr_ungated, mrr_insample_gated, mrr_loo_gated,
             loo_corrs, loo_classes, insample_corrs, insample_classes
    """
    all_sks = sorted(set(e["_sk"] for e in eps))
    by_sk   = {sk: [e for e in eps if e["_sk"] == sk] for sk in all_sks}

    # ── Full-corpus LR for ungated and in-sample gating ───────────────────────
    Xs_all = [episode_features(e) for e in eps]
    ys_all = [1 if e["_pc"] else 0 for e in eps]
    w_full, b_full = _lr_train(Xs_all, ys_all)

    # In-sample scores and correlations (OPEN-71 reference)
    insample_corrs   = {}
    insample_classes = {}
    for sk, grp in by_sk.items():
        scores  = [_predict(w_full, b_full, episode_features(e)) for e in grp]
        vcs     = [1 if e["_vc"] else 0 for e in grp]
        c = pearson(scores, vcs)
        insample_corrs[sk]   = c
        insample_classes[sk] = classify(c)

    # ── LOO: for each group, train on the rest ────────────────────────────────
    loo_corrs   = {}
    loo_classes = {}
    loo_scores  = {}   # {sk: [(episode, oog_score), ...]}

    for held_sk in all_sks:
        train_eps = [e for e in eps if e["_sk"] != held_sk]
        test_eps  = by_sk[held_sk]
        if not train_eps:
            loo_corrs[held_sk]   = float("nan")
            loo_classes[held_sk] = "neutral"
            loo_scores[held_sk]  = [(e, NEUTRAL_SCORE) for e in test_eps]
            continue
        Xs_tr = [episode_features(e) for e in train_eps]
        ys_tr = [1 if e["_pc"] else 0 for e in train_eps]
        if sum(ys_tr) == 0 or sum(ys_tr) == len(ys_tr):
            loo_corrs[held_sk]   = float("nan")
            loo_classes[held_sk] = "neutral"
            loo_scores[held_sk]  = [(e, NEUTRAL_SCORE) for e in test_eps]
            continue
        w_loo, b_loo = _lr_train(Xs_tr, ys_tr)
        scores = [_predict(w_loo, b_loo, episode_features(e)) for e in test_eps]
        vcs    = [1 if e["_vc"] else 0 for e in test_eps]
        c = pearson(scores, vcs)
        loo_corrs[held_sk]   = c
        loo_classes[held_sk] = classify(c)
        loo_scores[held_sk]  = list(zip(test_eps, scores))

    # ── Apply gating and compute MRRs ─────────────────────────────────────────

    # Static baseline
    for ep in eps: ep["_score"] = -ep["_seed"]
    mrr_static = mrr_groups(valid_groups(eps))

    # Ungated: full-corpus CE2 score on all episodes
    for ep in eps:
        ep["_score"] = _predict(w_full, b_full, episode_features(ep))
    mrr_ungated = mrr_groups(valid_groups(eps))

    # In-sample gated (OPEN-71 reference)
    for ep in eps:
        cls = insample_classes.get(ep["_sk"], "neutral")
        ep["_score"] = _predict(w_full, b_full, episode_features(ep)) if cls == "positive" else NEUTRAL_SCORE
    mrr_insample = mrr_groups(valid_groups(eps))

    # LOO-gated
    for sk, pairs in loo_scores.items():
        cls = loo_classes[sk]
        for ep, oog_score in pairs:
            # positive: use full-corpus CE2 score (same as OPEN-71; only classification changes)
            ep["_score"] = _predict(w_full, b_full, episode_features(ep)) if cls == "positive" else NEUTRAL_SCORE
    mrr_loo = mrr_groups(valid_groups(eps))

    return (mrr_static, mrr_ungated, mrr_insample, mrr_loo,
            loo_corrs, loo_classes, insample_corrs, insample_classes)


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    eps = load_episodes()
    n_pc = sum(1 for e in eps if e["_pc"])
    n_vc = sum(1 for e in eps if e["_vc"])
    print(f"Episodes: {len(eps)}  PC-positive: {n_pc}  VC-positive: {n_vc}")
    print()

    (mrr_s, mrr_u, mrr_is, mrr_loo,
     loo_corrs, loo_cls, is_corrs, is_cls) = run_loo(eps)

    # Per-group comparison table
    all_sks = sorted(set(e["_sk"] for e in eps))
    by_sk   = defaultdict(list)
    for ep in eps: by_sk[ep["_sk"]].append(ep)

    print("=== Per-group alignment: in-sample (OPEN-71) vs LOO (OPEN-71b) ===")
    print(f"  {'Scenario':<45}  {'n':>4}  {'IS corr':>8}  {'IS cls':>8}  {'LOO corr':>9}  {'LOO cls':>8}  {'flip?':>6}")
    flip_count = 0
    for sk in all_sks:
        n = len(by_sk[sk])
        ic = is_corrs.get(sk, float("nan"))
        lc = loo_corrs.get(sk, float("nan"))
        icls = is_cls.get(sk, "neutral")
        lcls = loo_cls.get(sk, "neutral")
        flipped = icls != lcls
        if flipped: flip_count += 1
        ic_str = f"{ic:+.4f}" if not math.isnan(ic) else "   nan"
        lc_str = f"{lc:+.4f}" if not math.isnan(lc) else "   nan"
        print(f"  {sk:<45}  {n:>4}  {ic_str:>8}  {icls:>8}  {lc_str:>9}  {lcls:>8}  {'YES' if flipped else '---':>6}")
    print(f"\n  Classification flips: {flip_count} / {len(all_sks)}")
    print()

    # Summary table
    print("=== MRR summary ===")
    print(f"  Static            : {mrr_s:.4f}  (OPEN-70 baseline)")
    print(f"  Ungated CE        : {mrr_u:.4f}  delta={mrr_u-mrr_s:+.4f}  (OPEN-70 L2)")
    print(f"  In-sample gated   : {mrr_is:.4f}  delta={mrr_is-mrr_s:+.4f}  (OPEN-71 reference)")
    print(f"  LOO-gated         : {mrr_loo:.4f}  delta={mrr_loo-mrr_s:+.4f}  vs ungated={mrr_loo-mrr_u:+.4f}  vs IS={mrr_loo-mrr_is:+.4f}")
    print()

    # Verdicts
    d_loo_static = mrr_loo - mrr_s
    l2_verdict = "GREEN"  if d_loo_static >= DELTA_THRESHOLD else (
                 "YELLOW" if d_loo_static > 0                else "RED")
    l1_verdict = "GREEN" if mrr_u < mrr_s and mrr_loo >= mrr_s - 0.001 else (
                 "PARTIAL" if mrr_loo >= mrr_s - 0.001 else "RED")
    overall = ("GREEN"   if l1_verdict=="GREEN" and l2_verdict=="GREEN" else
               "L1_ONLY" if l1_verdict=="GREEN" else "RED")

    print("=== Verdicts ===")
    print(f"  L1 (gating stops harm): ungated<static={mrr_u<mrr_s}, LOO-gated>=static={mrr_loo>=mrr_s-0.001} -> {l1_verdict}")
    print(f"  L2 (LOO-gated beats static >=+0.05): delta={d_loo_static:+.4f}, threshold=+{DELTA_THRESHOLD} -> {l2_verdict}")
    print(f"  Overall: {overall}")
    print()

    out = {
        "experiment": "OPEN-71b",
        "n_episodes": len(eps),
        "n_pc": n_pc,
        "n_vc": n_vc,
        "corr_thresholds": {"positive": CORR_POS, "negative": CORR_NEG},
        "per_group": {
            sk: {
                "n": len(by_sk[sk]),
                "insample_corr": is_corrs.get(sk), "insample_class": is_cls.get(sk),
                "loo_corr": loo_corrs.get(sk),     "loo_class":      loo_cls.get(sk),
                "classification_flipped": is_cls.get(sk) != loo_cls.get(sk),
            }
            for sk in all_sks
        },
        "n_flips": flip_count,
        "mrr_static":   mrr_s,
        "mrr_ungated":  mrr_u,
        "mrr_insample": mrr_is,
        "mrr_loo":      mrr_loo,
        "delta_loo_vs_static":  d_loo_static,
        "delta_loo_vs_ungated": mrr_loo - mrr_u,
        "delta_loo_vs_insample": mrr_loo - mrr_is,
        "l1_verdict":  l1_verdict,
        "l2_verdict":  l2_verdict,
        "overall_verdict": overall,
    }
    outpath = os.path.join(os.path.dirname(__file__), "open71b_loo_gating_results.json")
    with open(outpath, "w") as f: json.dump(out, f, indent=2)
    print(f"Results: {outpath}")
    print(f"Overall verdict: {overall}")

if __name__ == "__main__":
    main()
