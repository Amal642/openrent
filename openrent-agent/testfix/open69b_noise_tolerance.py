"""
OPEN-69b — Oracle noise tolerance test
Stress-test CE signal manufacture by corrupting CE2 labels at
0%, 5%, 10%, 20%, 30%, 40% and measuring when L2 transfer collapses.

Pre-committed verdict bands:
  GREEN:  L2 delta >= +0.05 survives through at least 10% noise
  YELLOW: survives 5% only
  RED:    collapses under any nonzero noise

Same setup as OPEN-69 (identical data, features, MRR calculation).
"""

import json, glob, math, os, random, sys
from collections import defaultdict

PILOT = os.path.join(os.path.dirname(__file__), "..", "pilot_matrix_results")
_NEG_SIGNALS = {"conversation_stalled", "phone_requested_too_early"}
NOISE_LEVELS = [0.0, 0.05, 0.10, 0.20, 0.30, 0.40]
DELTA_THRESHOLD = 0.05
N_SEEDS = 8
SEEDS = [71, 72, 73, 74, 75, 76, 77, 78]


# ── data ─────────────────────────────────────────────────────────────────────

def load_episodes():
    eps = []
    for jf in glob.glob(os.path.join(PILOT, "**", "*.jsonl"), recursive=True):
        try:
            with open(jf) as fh:
                for line in fh:
                    ep = json.loads(line)
                    if "turn_rows" in ep and "summary" in ep and len(ep["turn_rows"]) > 0:
                        s = ep["summary"]
                        ep["_vc"] = bool(s.get("viewing_confirmed_ever",
                                                s.get("final_state", "") == "viewing_confirmed"))
                        ep["_sk"] = ep.get("scenario_key", "unk")
                        ep["_seed"] = ep.get("seed", 0)
                        # clean CE2 labels (no noise)
                        ep["_ce2_clean"] = [
                            1 if (len(tr.get("flipped_signals", [])) > 0 and
                                  any(s not in _NEG_SIGNALS for s in tr.get("flipped_signals", [])))
                            else 0
                            for tr in ep["turn_rows"]
                        ]
                        eps.append(ep)
        except Exception:
            pass
    return eps


# ── feature extraction (identical to OPEN-69) ────────────────────────────────

_SPEAKER_MAP = {"actor": 0.0, "landlord": 0.0, "agent": 1.0}
_BRANCH_IDX = {
    "branch-1-initial": 0, "branch-2-phone-shared": 1,
    "branch-4-default-screening": 2, "branch-5-proactive-offer": 3,
    "branch-unclassified": 4, None: 5,
}

def turn_features(tr, n_turns):
    idx  = tr["turn_index_0based"] / max(n_turns - 1, 1)
    spk  = _SPEAKER_MAP.get(tr["speaker"], 0.0)
    aph  = float(tr.get("agent_asked_phone", False))
    mlen = min(len(tr.get("message", "")) / 500.0, 1.0)
    bvec = [0.0] * 6
    bvec[_BRANCH_IDX.get(tr.get("landlord_branch"), 5)] = 1.0
    return [idx, spk, aph, mlen] + bvec  # dim=10


# ── logistic regression ───────────────────────────────────────────────────────

def _sigmoid(x):
    return 1.0 / (1.0 + math.exp(-max(-60, min(60, x))))

def _dot(w, x):
    return sum(wi * xi for wi, xi in zip(w, x))

def _lr_train(Xs, ys, lr=0.05, epochs=300, l2=0.01):
    dim = len(Xs[0])
    w = [0.0] * dim; b = 0.0
    for _ in range(epochs):
        for x, y in zip(Xs, ys):
            p = _sigmoid(_dot(w, x) + b)
            g = p - y
            w = [wi - lr * (g * xi + l2 * wi) for wi, xi in zip(w, x)]
            b -= lr * g
    return w, b

def _lr_predict(w, b, x):
    return _sigmoid(_dot(w, x) + b)


# ── noise injection ───────────────────────────────────────────────────────────

def corrupt_labels(clean_labels, noise_rate, rng):
    """Flip each label independently with probability noise_rate."""
    return [
        (1 - lbl) if rng.random() < noise_rate else lbl
        for lbl in clean_labels
    ]


# ── AUC ──────────────────────────────────────────────────────────────────────

def auc(labels, scores):
    pos = [s for l, s in zip(labels, scores) if l == 1]
    neg = [s for l, s in zip(labels, scores) if l == 0]
    if not pos or not neg:
        return 0.5
    wins = sum(
        1.0 if p > n else (0.5 if p == n else 0.0)
        for p in pos for n in neg
    )
    return wins / (len(pos) * len(neg))


# ── MRR ──────────────────────────────────────────────────────────────────────

def mrr_groups(groups):
    rrs = []
    for eps_group in groups.values():
        ranked = sorted(eps_group, key=lambda e: -e["_score"])
        for rank, ep in enumerate(ranked, 1):
            if ep["_vc"]:
                rrs.append(1.0 / rank)
                break
        else:
            rrs.append(0.0)
    return sum(rrs) / len(rrs) if rrs else 0.0


def build_groups(eps, score_key="_score"):
    groups = defaultdict(list)
    for ep in eps:
        groups[ep["_sk"]].append(ep)
    # exclude groups with no positives
    return {sk: g for sk, g in groups.items() if any(e["_vc"] for e in g)}


# ── run one noise level ───────────────────────────────────────────────────────

def run_noise_level(eps, noise_rate, seeds):
    l1_aucs = []
    mrr_ce2_list = []
    mrr_static_list = []

    for seed in seeds:
        rng = random.Random(seed)

        # ── L1: 5-fold episode-out CV on (potentially noisy) CE2 labels ────
        n = len(eps)
        fold_size = n // 5
        shuffled = eps[:]
        rng.shuffle(shuffled)
        fold_labels = []; fold_scores = []
        for fold in range(5):
            lo = fold * fold_size
            hi = lo + fold_size if fold < 4 else n
            test_eps  = shuffled[lo:hi]
            train_eps = shuffled[:lo] + shuffled[hi:]
            Xs_tr, ys_tr = [], []
            for ep in train_eps:
                nt = len(ep["turn_rows"])
                noisy = corrupt_labels(ep["_ce2_clean"], noise_rate, rng)
                for tr, ce2 in zip(ep["turn_rows"], noisy):
                    Xs_tr.append(turn_features(tr, nt))
                    ys_tr.append(ce2)
            if sum(ys_tr) == 0 or sum(ys_tr) == len(ys_tr):
                continue
            w, b = _lr_train(Xs_tr, ys_tr)
            for ep in test_eps:
                nt = len(ep["turn_rows"])
                # evaluate against CLEAN labels (we want to know if model still
                # correctly predicts state advancement despite noisy training)
                for tr, ce2_clean in zip(ep["turn_rows"], ep["_ce2_clean"]):
                    sc = _lr_predict(w, b, turn_features(tr, nt))
                    fold_labels.append(ce2_clean)
                    fold_scores.append(sc)
        l1_aucs.append(auc(fold_labels, fold_scores))

        # ── L2: train on noisy CE2, score episodes, compute ER MRR ─────────
        Xs_all, ys_all = [], []
        for ep in eps:
            nt = len(ep["turn_rows"])
            noisy = corrupt_labels(ep["_ce2_clean"], noise_rate, rng)
            for tr, ce2 in zip(ep["turn_rows"], noisy):
                Xs_all.append(turn_features(tr, nt))
                ys_all.append(ce2)
        w, b = _lr_train(Xs_all, ys_all)
        for ep in eps:
            nt = len(ep["turn_rows"])
            probs = [_lr_predict(w, b, turn_features(tr, nt)) for tr in ep["turn_rows"]]
            ep["_score"] = sum(probs) / len(probs)

        valid_groups = build_groups(eps)
        mrr_ce2_list.append(mrr_groups(valid_groups))

        # static: rank by seed (deterministic, no-info baseline)
        static_groups = defaultdict(list)
        for ep in eps:
            ep["_score"] = -ep["_seed"]
            static_groups[ep["_sk"]].append(ep)
        valid_static = {sk: g for sk, g in static_groups.items() if any(e["_vc"] for e in g)}
        mrr_static_list.append(mrr_groups(valid_static))

    mean_l1  = sum(l1_aucs) / len(l1_aucs)
    mean_ce2 = sum(mrr_ce2_list) / len(mrr_ce2_list)
    mean_sta = sum(mrr_static_list) / len(mrr_static_list)
    delta    = mean_ce2 - mean_sta
    return {
        "noise": noise_rate,
        "l1_auc": mean_l1,
        "mrr_ce2": mean_ce2,
        "mrr_static": mean_sta,
        "delta": delta,
        "l1_green": mean_l1 >= 0.55,
        "l2_green": delta >= DELTA_THRESHOLD,
    }


# ── verdict ───────────────────────────────────────────────────────────────────

def verdict(rows):
    """
    GREEN:  L2 delta >= 0.05 through at least 10% noise
    YELLOW: survives 5% only
    RED:    collapses under any nonzero noise
    """
    by_noise = {r["noise"]: r for r in rows}
    passes_10 = by_noise.get(0.10, {}).get("l2_green", False)
    passes_05 = by_noise.get(0.05, {}).get("l2_green", False)
    passes_00 = by_noise.get(0.00, {}).get("l2_green", False)
    if not passes_00:
        return "RED (baseline failed)"
    if passes_10:
        return "GREEN"
    if passes_05:
        return "YELLOW"
    return "RED"


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    eps = load_episodes()
    print(f"Episodes: {len(eps)}  VC-positive: {sum(1 for e in eps if e['_vc'])}")
    print(f"CE2 positive turns (clean): "
          f"{sum(sum(e['_ce2_clean']) for e in eps)} / {sum(len(e['turn_rows']) for e in eps)}")
    print()
    print(f"{'Noise':>8}  {'L1 AUC':>9}  {'L2 MRR':>8}  {'Static':>8}  {'Delta':>8}  {'L2?':>6}")
    print("-" * 65)

    rows = []
    for noise in NOISE_LEVELS:
        row = run_noise_level(eps, noise, SEEDS)
        rows.append(row)
        l2_flag = "GREEN" if row["l2_green"] else "  ---"
        l1_flag = "GREEN" if row["l1_green"] else "  ---"
        print(f"  {noise*100:5.0f}%  "
              f"AUC={row['l1_auc']:.4f}({l1_flag:5})  "
              f"MRR={row['mrr_ce2']:.4f}  "
              f"sta={row['mrr_static']:.4f}  "
              f"d={row['delta']:+.4f}  "
              f"{l2_flag}")

    v = verdict(rows)
    print(f"\nVerdict: {v}")
    print(f"Pre-committed bands: GREEN=survives 10%, YELLOW=5% only, RED=any noise kills")

    out = {
        "experiment": "OPEN-69b",
        "n_episodes": len(eps),
        "n_seeds": N_SEEDS,
        "delta_threshold": DELTA_THRESHOLD,
        "noise_levels": NOISE_LEVELS,
        "rows": rows,
        "verdict": v,
    }
    out_path = os.path.join(os.path.dirname(__file__), "open69b_noise_tolerance_results.json")
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"Results: {out_path}")


if __name__ == "__main__":
    main()
