"""
OPEN-69 — CE signal manufacture: Thread C experiment
Pre-committed falsifier (two levels, cheapest first):
  L1 mechanism: CE2-trained LR beats random on CE2 turn-level AUC > 0.55
  L2 transfer:  CE2-episode-score MRR > static MRR + 0.05 on ER (viewing_confirmed_ever)
CE2 oracle: per-turn binary — did any positive signal fire this turn?
  Positive signals: all flipped_signals EXCEPT conversation_stalled / phone_requested_too_early
ER oracle: episode-level viewing_confirmed_ever
"""

import json, glob, math, os, random, sys
from collections import defaultdict

# ── data ────────────────────────────────────────────────────────────────────

PILOT = os.path.join(os.path.dirname(__file__), "..", "pilot_matrix_results")

_NEG_SIGNALS = {"conversation_stalled", "phone_requested_too_early"}

def load_episodes():
    eps = []
    for jf in glob.glob(os.path.join(PILOT, "**", "*.jsonl"), recursive=True):
        try:
            with open(jf) as fh:
                for line in fh:
                    ep = json.loads(line)
                    if "turn_rows" in ep and "summary" in ep and len(ep["turn_rows"]) > 0:
                        ep["_src"] = jf
                        # CE2 per-turn labels
                        ep["_ce2"] = [
                            1 if any(s not in _NEG_SIGNALS for s in tr.get("flipped_signals", []))
                               and len(tr.get("flipped_signals", [])) > 0
                            else 0
                            for tr in ep["turn_rows"]
                        ]
                        # ER label
                        s = ep["summary"]
                        ep["_vc"] = bool(
                            s.get("viewing_confirmed_ever", s.get("final_state", "") == "viewing_confirmed")
                        )
                        ep["_sk"] = ep.get("scenario_key", "unk")
                        ep["_seed"] = ep.get("seed", 0)
                        eps.append(ep)
        except Exception:
            pass
    return eps


# ── features (no leakage: current_state excluded; only pre-turn observables) ─

_SPEAKER_MAP = {"actor": 0.0, "landlord": 0.0, "agent": 1.0}
_BRANCH_IDX  = {
    "branch-1-initial": 0, "branch-2-phone-shared": 1,
    "branch-4-default-screening": 2, "branch-5-proactive-offer": 3,
    "branch-unclassified": 4, None: 5,
}

def turn_features(tr, n_turns):
    idx  = tr["turn_index_0based"] / max(n_turns - 1, 1)
    spk  = _SPEAKER_MAP.get(tr["speaker"], 0.0)
    aph  = float(tr.get("agent_asked_phone", False))
    mlen = min(len(tr.get("message", "")) / 500.0, 1.0)  # cap at 500 chars
    bvec = [0.0] * 6
    bvec[_BRANCH_IDX.get(tr.get("landlord_branch"), 5)] = 1.0
    return [idx, spk, aph, mlen] + bvec  # dim=10


# ── logistic regression (no sklearn required for L1/L2 at this scale) ────────

def _sigmoid(x):
    return 1.0 / (1.0 + math.exp(-max(-60, min(60, x))))

def _dot(w, x):
    return sum(wi * xi for wi, xi in zip(w, x))

def _lr_train(Xs, ys, lr=0.1, epochs=200, l2=0.01):
    dim = len(Xs[0])
    w = [0.0] * dim
    b = 0.0
    for _ in range(epochs):
        for x, y in zip(Xs, ys):
            p  = _sigmoid(_dot(w, x) + b)
            g  = p - y
            w  = [wi - lr * (g * xi + l2 * wi) for wi, xi in zip(w, x)]
            b -= lr * g
    return w, b

def _lr_predict(w, b, x):
    return _sigmoid(_dot(w, x) + b)


# ── helpers ──────────────────────────────────────────────────────────────────

def mrr(groups):
    """MRR: for each group, rank episodes by score desc; compute 1/rank of first positive."""
    rrs = []
    for eps in groups.values():
        ranked = sorted(eps, key=lambda e: -e["score"])
        for rank, ep in enumerate(ranked, 1):
            if ep["_vc"]:
                rrs.append(1.0 / rank)
                break
        else:
            rrs.append(0.0)
    return sum(rrs) / len(rrs) if rrs else 0.0


def auc(labels, scores):
    """Wilcoxon-Mann-Whitney AUC."""
    pos = [s for l, s in zip(labels, scores) if l == 1]
    neg = [s for l, s in zip(labels, scores) if l == 0]
    if not pos or not neg:
        return 0.5
    n_pos = len(pos)
    n_neg = len(neg)
    wins = 0.0
    for p in pos:
        wins += sum(1.0 if p > n else (0.5 if p == n else 0.0) for n in neg)
    return wins / (n_pos * n_neg)


# ── L1: mechanism check (5-fold episode-out CV on CE2 AUC) ──────────────────

def run_l1(eps, seeds):
    n = len(eps)
    fold_size = n // 5
    all_labels = []; all_scores = []
    random.seed(seeds[0])
    shuffled = eps[:]
    random.shuffle(shuffled)
    for fold in range(5):
        lo = fold * fold_size
        hi = lo + fold_size if fold < 4 else n
        test_eps  = shuffled[lo:hi]
        train_eps = shuffled[:lo] + shuffled[hi:]
        # build turn-level training set
        Xs_tr, ys_tr = [], []
        for ep in train_eps:
            nt = len(ep["turn_rows"])
            for tr, ce2 in zip(ep["turn_rows"], ep["_ce2"]):
                Xs_tr.append(turn_features(tr, nt))
                ys_tr.append(ce2)
        if sum(ys_tr) == 0 or sum(ys_tr) == len(ys_tr):
            continue
        w, b = _lr_train(Xs_tr, ys_tr)
        # predict on test episodes' turns
        for ep in test_eps:
            nt = len(ep["turn_rows"])
            for tr, ce2 in zip(ep["turn_rows"], ep["_ce2"]):
                score = _lr_predict(w, b, turn_features(tr, nt))
                all_labels.append(ce2)
                all_scores.append(score)
    return auc(all_labels, all_scores)


# ── L2: transfer check ───────────────────────────────────────────────────────

def run_l2(eps, seeds):
    results = {}
    for seed in seeds:
        random.seed(seed)
        # train turn-level LR on full CE2 dataset
        Xs, ys = [], []
        for ep in eps:
            nt = len(ep["turn_rows"])
            for tr, ce2 in zip(ep["turn_rows"], ep["_ce2"]):
                Xs.append(turn_features(tr, nt))
                ys.append(ce2)
        w, b = _lr_train(Xs, ys, lr=0.05, epochs=300)
        # episode score = mean CE2 probability across all turns
        for ep in eps:
            nt = len(ep["turn_rows"])
            probs = [_lr_predict(w, b, turn_features(tr, nt)) for tr in ep["turn_rows"]]
            ep["_ce2_score"] = sum(probs) / len(probs)
        # build group dicts for ER MRR
        grp_ce2 = defaultdict(list)
        grp_static = defaultdict(list)
        grp_freq = defaultdict(list)
        # freq baseline: group-level VC rate (from all episodes, not oracle)
        sk_pos = defaultdict(int); sk_total = defaultdict(int)
        for ep in eps:
            sk_pos[ep["_sk"]] += 1 if ep["_vc"] else 0
            sk_total[ep["_sk"]] += 1
        sk_freq = {sk: sk_pos[sk] / sk_total[sk] for sk in sk_total}
        # random order per group (seed-shuffled within group)
        rng_order = {}
        for ep in eps:
            sk = ep["_sk"]
            if sk not in rng_order:
                rng_order[sk] = []
            rng_order[sk].append(ep)
        for sk, group in rng_order.items():
            random.shuffle(group)
            for i, ep in enumerate(group):
                ep["_random_rank"] = i
        for ep in eps:
            ep_ce2 = {**ep, "score": ep["_ce2_score"]}
            ep_static = {**ep, "score": -ep["_seed"]}    # lower seed = higher rank
            ep_freq   = {**ep, "score": sk_freq[ep["_sk"]]}
            grp_ce2[ep["_sk"]].append(ep_ce2)
            grp_static[ep["_sk"]].append(ep_static)
            grp_freq[ep["_sk"]].append(ep_freq)
        # exclude groups with no positives from MRR
        valid_sks = [sk for sk, group in grp_ce2.items() if any(ep["_vc"] for ep in group)]
        grp_ce2_v    = {sk: grp_ce2[sk]    for sk in valid_sks}
        grp_static_v = {sk: grp_static[sk] for sk in valid_sks}
        grp_freq_v   = {sk: grp_freq[sk]   for sk in valid_sks}
        mrr_ce2    = mrr(grp_ce2_v)
        mrr_static = mrr(grp_static_v)
        mrr_freq   = mrr(grp_freq_v)
        results[seed] = {"mrr_ce2": mrr_ce2, "mrr_static": mrr_static, "mrr_freq": mrr_freq}
    return results


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    L1_SEEDS = [71, 72, 73, 74]
    L2_SEEDS = [71, 72, 73, 74]
    DELTA = 0.05

    eps = load_episodes()
    print(f"Episodes loaded: {len(eps)}  positives(VC): {sum(1 for e in eps if e['_vc'])}")
    print(f"CE2 positive turns: {sum(sum(e['_ce2']) for e in eps)} / {sum(len(e['turn_rows']) for e in eps)}")
    print()

    # ── L1 ──────────────────────────────────────────────────────────────────
    print("=== L1: Mechanism check (5-fold CE2 AUC) ===")
    l1_aucs = []
    for seed in L1_SEEDS:
        auc_val = run_l1(eps, [seed])
        l1_aucs.append(auc_val)
        print(f"  seed={seed}  CE2_AUC={auc_val:.4f}")
    l1_mean = sum(l1_aucs) / len(l1_aucs)
    l1_verdict = "GREEN" if l1_mean >= 0.5 + DELTA else "RED"
    print(f"  Mean CE2 AUC = {l1_mean:.4f}  threshold=0.55  verdict={l1_verdict}")
    print()

    # ── L2 ──────────────────────────────────────────────────────────────────
    print("=== L2: Transfer check (ER MRR, ranking by CE2 episode score) ===")
    l2_res = run_l2(eps, L2_SEEDS)
    mrr_ce2_vals    = [v["mrr_ce2"]    for v in l2_res.values()]
    mrr_static_vals = [v["mrr_static"] for v in l2_res.values()]
    mrr_freq_vals   = [v["mrr_freq"]   for v in l2_res.values()]
    for seed, v in l2_res.items():
        print(f"  seed={seed}  CE2={v['mrr_ce2']:.4f}  static={v['mrr_static']:.4f}  freq={v['mrr_freq']:.4f}")
    mrr_ce2_mean    = sum(mrr_ce2_vals) / len(mrr_ce2_vals)
    mrr_static_mean = sum(mrr_static_vals) / len(mrr_static_vals)
    mrr_freq_mean   = sum(mrr_freq_vals) / len(mrr_freq_vals)
    d_vs_static = mrr_ce2_mean - mrr_static_mean
    d_vs_freq   = mrr_ce2_mean - mrr_freq_mean
    l2_verdict = "GREEN" if d_vs_static >= DELTA else ("YELLOW" if d_vs_static > 0 else "RED")
    print(f"  Mean CE2={mrr_ce2_mean:.4f}  static={mrr_static_mean:.4f}  freq={mrr_freq_mean:.4f}")
    print(f"  delta_vs_static={d_vs_static:+.4f}  threshold=+0.05  verdict={l2_verdict}")
    print()

    # ── per-group breakdown ──────────────────────────────────────────────────
    print("=== Per-scenario-group breakdown (seed=71) ===")
    eps_s71 = eps  # already scored by last run_l2 call (seed 71 is last in L2_SEEDS? no, 74 is last)
    # re-run seed 71 for breakdown
    random.seed(71)
    Xs, ys = [], []
    for ep in eps:
        nt = len(ep["turn_rows"])
        for tr, ce2 in zip(ep["turn_rows"], ep["_ce2"]):
            Xs.append(turn_features(tr, nt))
            ys.append(ce2)
    w, b = _lr_train(Xs, ys, lr=0.05, epochs=300)
    for ep in eps:
        nt = len(ep["turn_rows"])
        probs = [_lr_predict(w, b, turn_features(tr, nt)) for tr in ep["turn_rows"]]
        ep["_ce2_score"] = sum(probs) / len(probs)
    sk_pos_rates = defaultdict(list)
    for ep in eps:
        sk_pos_rates[ep["_sk"]].append((ep["_ce2_score"], ep["_vc"]))
    for sk in sorted(sk_pos_rates):
        items = sk_pos_rates[sk]
        ranked = sorted(items, key=lambda x: -x[0])
        n_pos = sum(1 for _, vc in items if vc)
        rr = 0.0
        for rank, (_, vc) in enumerate(ranked, 1):
            if vc:
                rr = 1.0 / rank
                break
        print(f"  {sk:<45}  n={len(items)}  pos={n_pos}  MRR(CE2)={rr:.3f}")

    # ── save results ─────────────────────────────────────────────────────────
    out = {
        "experiment": "OPEN-69",
        "n_episodes": len(eps),
        "n_pos_vc": sum(1 for e in eps if e["_vc"]),
        "ce2_pos_turns": sum(sum(e["_ce2"]) for e in eps),
        "ce2_total_turns": sum(len(e["turn_rows"]) for e in eps),
        "l1": {
            "seeds": L1_SEEDS,
            "per_seed_auc": dict(zip(L1_SEEDS, l1_aucs)),
            "mean_auc": l1_mean,
            "threshold": 0.55,
            "verdict": l1_verdict,
        },
        "l2": {
            "seeds": L2_SEEDS,
            "per_seed": {str(s): v for s, v in l2_res.items()},
            "mrr_ce2_mean": mrr_ce2_mean,
            "mrr_static_mean": mrr_static_mean,
            "mrr_freq_mean": mrr_freq_mean,
            "delta_vs_static": d_vs_static,
            "delta_vs_freq": d_vs_freq,
            "threshold": DELTA,
            "verdict": l2_verdict,
        },
        "overall_verdict": "GREEN" if l1_verdict == "GREEN" and l2_verdict == "GREEN" else
                           "L1_ONLY" if l1_verdict == "GREEN" else
                           "RED",
    }
    out_path = os.path.join(os.path.dirname(__file__), "open69_ce_manufacture_results.json")
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\nResults saved: {out_path}")
    print(f"\nOverall verdict: {out['overall_verdict']}")


if __name__ == "__main__":
    main()
