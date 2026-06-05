"""
OPEN-70: CE->ER transfer analysis.
CE2 oracle (training label): phone_captured (episode-level)
ER oracle  (eval label):     viewing_confirmed_ever

Data: existing 108 pilot episodes (a3-a6, LLM-based actors).
Corpus expansion BLOCKED: scripted LandlordActorV2 deterministically
produces PC under corpus_number_capture_v1 and VC under viewing_first_v1
-- no mixed-outcome corpus is achievable without LLM-based actor data.

Pre-committed falsifier:
  L1: LR trained on PC CE2 labels, 5-fold episode-out AUC on PC > 0.55
  L2: CE2-episode-score MRR > static MRR + 0.05 on VC ER labels

Additional analysis: per-group PC/VC cross-tab; CE2 score vs VC outcome;
PC=True/VC=False vs PC=True/VC=True feature comparison.
"""

import json, glob, math, os, random
from collections import defaultdict
from dataclasses import asdict

PILOT = os.path.join(os.path.dirname(__file__), "..", "pilot_matrix_results")
_NEG_SIGNALS = {"conversation_stalled", "phone_requested_too_early"}

SEEDS = [71, 72, 73, 74, 75, 76, 77, 78]
DELTA = 0.05


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


# ── features (episode-level aggregate) ───────────────────────────────────────

_SPEAKER  = {"actor": 0.0, "landlord": 0.0, "agent": 1.0}
_BRANCH   = {"branch-1-initial":0,"branch-2-phone-shared":1,
             "branch-4-default-screening":2,"branch-5-proactive-offer":3,
             "branch-unclassified":4,None:5}
_STATES   = ["screening","viewing_negotiation","viewing_confirmed","phone_captured","stalled"]

def episode_features(ep: dict) -> list[float]:
    rows = ep["turn_rows"]
    n = max(len(rows), 1)
    # per-turn features averaged over episode
    idx_mean   = sum(r["turn_index_0based"] for r in rows) / n / max(n-1, 1)
    spk_mean   = sum(_SPEAKER.get(r["speaker"], 0.0) for r in rows) / n
    aph_frac   = sum(1 for r in rows if r.get("agent_asked_phone")) / n
    mlen_mean  = sum(min(len(r.get("message",""))/500.0, 1.0) for r in rows) / n
    # fraction of turns in each state
    state_frac = [sum(1 for r in rows if r.get("current_state","") == s) / n for s in _STATES]
    # fraction of actor turns in each branch
    actor_rows = [r for r in rows if r["speaker"] == "actor"]
    na = max(len(actor_rows), 1)
    branch_frac = [sum(1 for r in actor_rows if r.get("landlord_branch") == k.replace("branch-","branch-").split(":")[0]) / na
                   for k in ["branch-1-initial","branch-2-phone-shared","branch-4-default-screening","branch-5-proactive-offer"]]
    # CE2 signal fraction: fraction of turns where any positive signal flipped
    ce2_clean = [1 if (len(r.get("flipped_signals",[])) > 0 and
                       any(s not in _NEG_SIGNALS for s in r.get("flipped_signals",[]))) else 0
                 for r in rows]
    ce2_frac   = sum(ce2_clean) / n
    n_turns_norm = n / 7.0  # normalised by max observed turns
    return [idx_mean, spk_mean, aph_frac, mlen_mean] + state_frac + branch_frac + [ce2_frac, n_turns_norm]
    # dim = 4 + 5 + 4 + 2 = 15


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


# ── AUC / MRR ─────────────────────────────────────────────────────────────────

def auc(labels, scores):
    pos = [s for l,s in zip(labels,scores) if l==1]
    neg = [s for l,s in zip(labels,scores) if l==0]
    if not pos or not neg: return 0.5
    wins = sum(1.0 if p>n else (0.5 if p==n else 0.0) for p in pos for n in neg)
    return wins / (len(pos) * len(neg))

def mrr_groups(groups: dict) -> float:
    rrs = []
    for group in groups.values():
        ranked = sorted(group, key=lambda e: -e["_score"])
        for rank, ep in enumerate(ranked, 1):
            if ep["_vc"]:
                rrs.append(1.0/rank); break
        else:
            rrs.append(0.0)
    return sum(rrs)/len(rrs) if rrs else 0.0

def valid_groups(eps: list) -> dict:
    g = defaultdict(list)
    for ep in eps: g[ep["_sk"]].append(ep)
    return {sk: v for sk, v in g.items() if any(e["_vc"] for e in v)}


# ── L1 ────────────────────────────────────────────────────────────────────────

def run_l1(eps, seeds):
    results = []
    n = len(eps)
    fold_size = n // 5
    for seed in seeds:
        rng = random.Random(seed)
        shuffled = eps[:]
        rng.shuffle(shuffled)
        labels = []; scores = []
        for fold in range(5):
            lo = fold * fold_size
            hi = lo + fold_size if fold < 4 else n
            test  = shuffled[lo:hi]
            train = shuffled[:lo] + shuffled[hi:]
            Xs = [episode_features(e) for e in train]
            ys = [1 if e["_pc"] else 0 for e in train]
            if sum(ys) == 0 or sum(ys) == len(ys): continue
            w, b = _lr_train(Xs, ys)
            for ep in test:
                labels.append(1 if ep["_pc"] else 0)
                scores.append(_predict(w, b, episode_features(ep)))
        results.append(auc(labels, scores))
    return results


# ── L2 ────────────────────────────────────────────────────────────────────────

def run_l2(eps, seeds):
    results = []
    for seed in seeds:
        rng = random.Random(seed)
        Xs = [episode_features(e) for e in eps]
        ys = [1 if e["_pc"] else 0 for e in eps]
        w, b = _lr_train(Xs, ys)
        for ep in eps:
            ep["_score"] = _predict(w, b, episode_features(ep))

        ce2_grps = valid_groups(eps)
        mrr_ce2 = mrr_groups(ce2_grps)

        # static: seed-based rank
        for ep in eps: ep["_score"] = -ep["_seed"]
        sta_grps = valid_groups(eps)
        mrr_static = mrr_groups(sta_grps)
        results.append({"mrr_ce2": mrr_ce2, "mrr_static": mrr_static})
    return results


# ── PC/VC cross-tab per group ─────────────────────────────────────────────────

def crosstab(eps):
    by_sk = defaultdict(lambda: {"pc_vc":0,"pc_nvc":0,"npc_vc":0,"npc_nvc":0})
    for ep in eps:
        k = ("pc" if ep["_pc"] else "npc") + "_" + ("vc" if ep["_vc"] else "nvc")
        by_sk[ep["_sk"]][k] += 1
    return dict(by_sk)


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    eps = load_episodes()
    print(f"Episodes: {len(eps)}  PC-positive: {sum(1 for e in eps if e['_pc'])}  VC-positive: {sum(1 for e in eps if e['_vc'])}")
    print()

    # Cross-tab
    print("=== PC/VC cross-tab by scenario group ===")
    ct = crosstab(eps)
    print(f"  {'Scenario':<45}  {'PC+VC+':>6}  {'PC+VC-':>6}  {'PC-VC+':>6}  {'PC-VC-':>6}")
    grand = {"pc_vc":0,"pc_nvc":0,"npc_vc":0,"npc_nvc":0}
    for sk in sorted(ct):
        r = ct[sk]
        for k in grand: grand[k] += r.get(k,0)
        print(f"  {sk:<45}  {r.get('pc_vc',0):>6}  {r.get('pc_nvc',0):>6}  {r.get('npc_vc',0):>6}  {r.get('npc_nvc',0):>6}")
    print(f"  {'TOTAL':<45}  {grand['pc_vc']:>6}  {grand['pc_nvc']:>6}  {grand['npc_vc']:>6}  {grand['npc_nvc']:>6}")
    print()

    # L1
    print("=== L1: Mechanism (AUC on PC CE2 label) ===")
    l1 = run_l1(eps, SEEDS)
    l1_mean = sum(l1)/len(l1)
    for seed, v in zip(SEEDS, l1): print(f"  seed={seed}  AUC={v:.4f}")
    l1_verdict = "GREEN" if l1_mean >= 0.55 else "RED"
    print(f"  Mean AUC = {l1_mean:.4f}  threshold=0.55  verdict={l1_verdict}")
    print()

    # L2
    print("=== L2: Transfer (ER MRR from PC CE2 episode score) ===")
    l2 = run_l2(eps, SEEDS)
    mrr_ce2_vals    = [v["mrr_ce2"]    for v in l2]
    mrr_static_vals = [v["mrr_static"] for v in l2]
    for seed, v in zip(SEEDS, l2):
        print(f"  seed={seed}  CE2={v['mrr_ce2']:.4f}  static={v['mrr_static']:.4f}  delta={v['mrr_ce2']-v['mrr_static']:+.4f}")
    ce2_mean = sum(mrr_ce2_vals)/len(mrr_ce2_vals)
    sta_mean = sum(mrr_static_vals)/len(mrr_static_vals)
    delta = ce2_mean - sta_mean
    l2_verdict = "GREEN" if delta >= DELTA else ("YELLOW" if delta > 0 else "RED")
    print(f"  Mean CE2={ce2_mean:.4f}  static={sta_mean:.4f}  delta={delta:+.4f}  threshold=+0.05  verdict={l2_verdict}")
    print()

    # Per-group breakdown (seed 71)
    print("=== Per-group breakdown (seed=71) ===")
    Xs = [episode_features(e) for e in eps]
    ys = [1 if e["_pc"] else 0 for e in eps]
    w, b = _lr_train(Xs, ys)
    for ep in eps: ep["_score"] = _predict(w, b, episode_features(ep))
    ct2 = defaultdict(lambda: {"eps":[],"pc":0,"vc":0})
    for ep in eps:
        ct2[ep["_sk"]]["eps"].append(ep)
        if ep["_pc"]: ct2[ep["_sk"]]["pc"] += 1
        if ep["_vc"]: ct2[ep["_sk"]]["vc"] += 1
    print(f"  {'Scenario':<45}  {'n':>4}  {'PC':>4}  {'VC':>4}  {'MRR(CE2)':>10}  {'Correlation':>12}")
    for sk in sorted(ct2):
        g = ct2[sk]
        grp_eps = g["eps"]
        ranked = sorted(grp_eps, key=lambda e: -e["_score"])
        rr = 0.0
        for rank, ep in enumerate(ranked, 1):
            if ep["_vc"]: rr = 1.0/rank; break
        # Pearson corr between CE2 score and VC label (direction of transfer)
        scores = [e["_score"] for e in grp_eps]
        vc_lbls = [1 if e["_vc"] else 0 for e in grp_eps]
        mean_s = sum(scores)/len(scores); mean_v = sum(vc_lbls)/len(vc_lbls)
        cov = sum((s-mean_s)*(v-mean_v) for s,v in zip(scores,vc_lbls))
        std_s = math.sqrt(sum((s-mean_s)**2 for s in scores)+1e-9)
        std_v = math.sqrt(sum((v-mean_v)**2 for v in vc_lbls)+1e-9)
        corr  = cov / (std_s * std_v)
        print(f"  {sk:<45}  {len(grp_eps):>4}  {g['pc']:>4}  {g['vc']:>4}  {rr:>10.3f}  {corr:>12.4f}")

    # Save
    out = {
        "experiment": "OPEN-70",
        "n_episodes": len(eps),
        "n_pc": sum(1 for e in eps if e["_pc"]),
        "n_vc": sum(1 for e in eps if e["_vc"]),
        "crosstab_global": grand,
        "l1": {"mean_auc": l1_mean, "verdict": l1_verdict, "per_seed": dict(zip(SEEDS, l1))},
        "l2": {
            "mrr_ce2_mean": ce2_mean, "mrr_static_mean": sta_mean,
            "delta": delta, "threshold": DELTA, "verdict": l2_verdict,
            "per_seed": [{"seed":s,"mrr_ce2":v["mrr_ce2"],"mrr_static":v["mrr_static"]} for s,v in zip(SEEDS,l2)],
        },
        "overall_verdict": (
            "GREEN" if l1_verdict=="GREEN" and l2_verdict=="GREEN" else
            "L1_ONLY" if l1_verdict=="GREEN" else "RED"
        ),
        "corpus_expansion_status": "BLOCKED — scripted LandlordActorV2 deterministically routes to PC under corpus_number_capture_v1 and VC under viewing_first_v1; no mixed corpus achievable without LLM-based actor data",
    }
    outpath = os.path.join(os.path.dirname(__file__), "open70_ce_er_results.json")
    with open(outpath, "w") as f: json.dump(out, f, indent=2)
    print(f"\nResults: {outpath}")
    print(f"Overall verdict: {out['overall_verdict']}")

if __name__ == "__main__":
    main()
