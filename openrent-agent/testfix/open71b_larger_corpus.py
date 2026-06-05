"""
OPEN-71b — larger corpus replication.

Data: a5_matrix + a6_matrix + a7_corpus_preloaded (210 episodes).
  Labels: phone_captured (CE/PC), viewing_booked (ER/VC).
  Features: 4-dim dimension_scores (answered_landlord_naturally,
            phone_timing_ok, safe_phone_capture, viewing_progressed).
  Groups: 9 scenario_keys (s02/s04/s05 × brusque/cooperative/suspicious).

Same procedure as OPEN-71b (LOO alignment gating):
  For each group g:
    - Train LR on other groups (PC labels)
    - Score g with OOG model
    - Classify g (LOO corr): positive > +0.05, negative < -0.05, neutral else
  Apply gating: positive groups use CE2 score, others get 0.5.
  Compare: static / ungated / LOO-gated.

Same thresholds as OPEN-71/71b (frozen, not re-tuned):
  CORR_POS = +0.05, CORR_NEG = -0.05
  GREEN: gated delta vs static >= +0.05
"""

import json, glob, math, os
from collections import defaultdict

DATA_DIRS = [
    os.path.join(os.path.dirname(__file__), "..", "pilot_matrix_results", d)
    for d in ["a5_matrix", "a6_matrix", "a7_corpus_preloaded"]
]
CORR_POS =  0.05
CORR_NEG = -0.05
NEUTRAL_SCORE = 0.5
DELTA_THRESHOLD = 0.05
DIM_KEYS = ["answered_landlord_naturally", "phone_timing_ok",
            "safe_phone_capture", "viewing_progressed"]


# ── data ─────────────────────────────────────────────────────────────────────

def load_episodes():
    eps = []
    for d in DATA_DIRS:
        jf = os.path.join(d, "trials.jsonl")
        if not os.path.exists(jf):
            continue
        with open(jf) as fh:
            for line in fh:
                ep = json.loads(line.strip())
                if not ep.get("dimension_scores"):
                    continue
                ep["_pc"]   = bool(ep.get("phone_captured", False))
                ep["_vc"]   = bool(ep.get("viewing_booked", False))
                ep["_sk"]   = ep.get("scenario_key", "unk")
                ep["_seed"] = ep.get("seed", 0)
                eps.append(ep)
    return eps


def episode_features(ep):
    d = ep.get("dimension_scores", {})
    return [float(d.get(k, 0.0)) for k in DIM_KEYS]


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
    for grp in groups.values():
        ranked = sorted(grp, key=lambda e: -e["_score"])
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
    all_sks = sorted(set(e["_sk"] for e in eps))
    by_sk   = {sk: [e for e in eps if e["_sk"] == sk] for sk in all_sks}

    # Full-corpus LR (for ungated and in-sample reference)
    Xs_all = [episode_features(e) for e in eps]
    ys_all = [1 if e["_pc"] else 0 for e in eps]
    w_full, b_full = _lr_train(Xs_all, ys_all)

    insample_corrs = {}
    insample_cls   = {}
    for sk, grp in by_sk.items():
        scores = [_predict(w_full, b_full, episode_features(e)) for e in grp]
        vcs    = [1 if e["_vc"] else 0 for e in grp]
        c = pearson(scores, vcs)
        insample_corrs[sk] = c
        insample_cls[sk]   = classify(c)

    loo_corrs   = {}
    loo_cls     = {}
    loo_scores  = {}

    for held_sk in all_sks:
        train_eps = [e for e in eps if e["_sk"] != held_sk]
        test_eps  = by_sk[held_sk]
        Xs_tr = [episode_features(e) for e in train_eps]
        ys_tr = [1 if e["_pc"] else 0 for e in train_eps]
        if not train_eps or sum(ys_tr) == 0 or sum(ys_tr) == len(ys_tr):
            loo_corrs[held_sk]  = float("nan")
            loo_cls[held_sk]    = "neutral"
            loo_scores[held_sk] = [(e, NEUTRAL_SCORE) for e in test_eps]
            continue
        w_loo, b_loo = _lr_train(Xs_tr, ys_tr)
        scores = [_predict(w_loo, b_loo, episode_features(e)) for e in test_eps]
        vcs    = [1 if e["_vc"] else 0 for e in test_eps]
        c = pearson(scores, vcs)
        loo_corrs[held_sk]  = c
        loo_cls[held_sk]    = classify(c)
        loo_scores[held_sk] = list(zip(test_eps, scores))

    # Static
    for ep in eps: ep["_score"] = -ep["_seed"]
    mrr_static = mrr_groups(valid_groups(eps))

    # Ungated
    for ep in eps: ep["_score"] = _predict(w_full, b_full, episode_features(ep))
    mrr_ungated = mrr_groups(valid_groups(eps))

    # In-sample gated (reference)
    for ep in eps:
        cls = insample_cls.get(ep["_sk"], "neutral")
        ep["_score"] = _predict(w_full, b_full, episode_features(ep)) if cls == "positive" else NEUTRAL_SCORE
    mrr_insample = mrr_groups(valid_groups(eps))

    # LOO-gated
    for sk, pairs in loo_scores.items():
        cls = loo_cls[sk]
        for ep, _ in pairs:
            ep["_score"] = _predict(w_full, b_full, episode_features(ep)) if cls == "positive" else NEUTRAL_SCORE
    mrr_loo = mrr_groups(valid_groups(eps))

    return (mrr_static, mrr_ungated, mrr_insample, mrr_loo,
            loo_corrs, loo_cls, insample_corrs, insample_cls)


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    eps = load_episodes()
    n_pc = sum(1 for e in eps if e["_pc"])
    n_vc = sum(1 for e in eps if e["_vc"])
    print(f"Episodes: {len(eps)}  PC-positive: {n_pc}  VC-positive: {n_vc}")
    print(f"Features: {DIM_KEYS}")
    print()

    (mrr_s, mrr_u, mrr_is, mrr_loo,
     loo_corrs, loo_cls, is_corrs, is_cls) = run_loo(eps)

    all_sks = sorted(set(e["_sk"] for e in eps))
    by_sk = defaultdict(list)
    for ep in eps: by_sk[ep["_sk"]].append(ep)

    print("=== Per-group alignment: in-sample vs LOO ===")
    print(f"  {'Scenario':<45}  {'n':>4}  {'PC':>4}  {'VC':>4}  {'IS corr':>8}  {'IS cls':>8}  {'LOO corr':>9}  {'LOO cls':>8}  {'flip?':>6}")
    flip_count = 0
    for sk in all_sks:
        g  = by_sk[sk]
        pc = sum(1 for e in g if e["_pc"])
        vc = sum(1 for e in g if e["_vc"])
        ic = is_corrs.get(sk, float("nan"))
        lc = loo_corrs.get(sk, float("nan"))
        icls = is_cls.get(sk, "neutral")
        lcls = loo_cls.get(sk, "neutral")
        flipped = icls != lcls
        if flipped: flip_count += 1
        ic_str = f"{ic:+.4f}" if not math.isnan(ic) else "   nan"
        lc_str = f"{lc:+.4f}" if not math.isnan(lc) else "   nan"
        print(f"  {sk:<45}  {len(g):>4}  {pc:>4}  {vc:>4}  {ic_str:>8}  {icls:>8}  {lc_str:>9}  {lcls:>8}  {'YES' if flipped else '---':>6}")
    print(f"\n  Classification flips: {flip_count} / {len(all_sks)}")
    print()

    # Valid groups for MRR
    vg = {sk: by_sk[sk] for sk in all_sks if any(e["_vc"] for e in by_sk[sk])}
    print(f"Valid groups (VC>0): {sorted(vg.keys())}")
    print()

    d_loo_static  = mrr_loo - mrr_s
    d_loo_ungated = mrr_loo - mrr_u

    print("=== MRR summary ===")
    print(f"  Static          : {mrr_s:.4f}")
    print(f"  Ungated CE      : {mrr_u:.4f}  delta={mrr_u-mrr_s:+.4f}")
    print(f"  In-sample gated : {mrr_is:.4f}  delta={mrr_is-mrr_s:+.4f}")
    print(f"  LOO-gated       : {mrr_loo:.4f}  delta={d_loo_static:+.4f}  vs_ungated={d_loo_ungated:+.4f}  vs_IS={mrr_loo-mrr_is:+.4f}")
    print()

    l1_verdict = "GREEN" if mrr_u < mrr_s and mrr_loo >= mrr_s - 0.001 else (
                 "PARTIAL" if mrr_loo >= mrr_s - 0.001 else "RED")
    l2_verdict = "GREEN"  if d_loo_static >= DELTA_THRESHOLD else (
                 "YELLOW" if d_loo_static > 0                else "RED")
    overall    = ("GREEN"   if l1_verdict == "GREEN" and l2_verdict == "GREEN" else
                  "L1_ONLY" if l1_verdict == "GREEN" else "RED")

    print("=== Verdicts ===")
    print(f"  L1: ungated<static={mrr_u<mrr_s}, LOO-gated>=static={mrr_loo>=mrr_s-0.001} -> {l1_verdict}")
    print(f"  L2: LOO-gated delta={d_loo_static:+.4f} threshold=+{DELTA_THRESHOLD} -> {l2_verdict}")
    print(f"  Overall: {overall}")
    print()

    out = {
        "experiment": "OPEN-71b-larger-corpus",
        "data_sources": ["a5_matrix", "a6_matrix", "a7_corpus_preloaded"],
        "n_episodes": len(eps),
        "n_pc": n_pc, "n_vc": n_vc,
        "features": DIM_KEYS,
        "corr_thresholds": {"positive": CORR_POS, "negative": CORR_NEG},
        "per_group": {
            sk: {
                "n": len(by_sk[sk]),
                "pc": sum(1 for e in by_sk[sk] if e["_pc"]),
                "vc": sum(1 for e in by_sk[sk] if e["_vc"]),
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
        "delta_loo_vs_static":   d_loo_static,
        "delta_loo_vs_ungated":  d_loo_ungated,
        "delta_loo_vs_insample": mrr_loo - mrr_is,
        "l1_verdict": l1_verdict,
        "l2_verdict": l2_verdict,
        "overall_verdict": overall,
    }
    outpath = os.path.join(os.path.dirname(__file__), "open71b_larger_corpus_results.json")
    with open(outpath, "w") as f: json.dump(out, f, indent=2)
    print(f"Results: {outpath}")
    print(f"Overall verdict: {overall}")

if __name__ == "__main__":
    main()
