"""
testfix.localizer_learned
-------------------------
Learned localizer for OPEN-52.

Trains a simple logistic regression on per-candidate features from
localizer_training.jsonl, evaluated via LOO-CV on all available cases.

Training signal  : is_true_B (1 for true helper B, 0 for all distractors)
Model            : logistic regression, scipy.optimize.minimize L-BFGS-B
Regularization   : L2, lambda=0.5 (excludes bias term)
Evaluation       : LOO-CV top-1/top-3/top-5 accuracy + MRR vs embedding baseline

Features per candidate (8 + bias):
  emb_score         continuous cosine similarity (0 if not in embedding top-10)
  bm25_score        continuous BM25 score
  emb_rank_norm     1/emb_rank (0 if not ranked)
  bm25_rank_norm    1/bm25_rank (0 if not ranked)
  in_call_graph     binary — directly called by entry-point A
  name_in_query     binary — function name appears in test source + error
  starts_with_underscore  binary — private helper signal
  same_file_as_entry      binary — co-location signal
  bias              constant 1.0

§S4 precommit threshold
  Learned localizer must beat embedding top-1 by ≥15 pp on ≥20 held-out cases.
  Do NOT claim self-learning until this criterion is met on ≥20 cases.

Usage (from openrent-agent/):
    python testfix/localizer_learned.py [--training testfix/localizer_training.jsonl]
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from scipy.optimize import minimize

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TRAINING = ROOT / "testfix/localizer_training.jsonl"
RESULTS_OUT = ROOT / "testfix/localizer_learned_results.json"

# Indices of continuous features that will be z-score normalised
_CONTINUOUS_IDX = [0, 1, 2, 3, 4]  # emb_score, bm25_score, emb_rank_norm, bm25_rank_norm, cg_rank_norm

FEATURE_NAMES = [
    "emb_score",
    "bm25_score",
    "emb_rank_norm",
    "bm25_rank_norm",
    "cg_rank_norm",
    "in_call_graph",
    "name_in_query",
    "starts_with_underscore",
    "same_file_as_entry",
    "bias",
]


# ── features ──────────────────────────────────────────────────────────────────

def _feature_vector(candidate: dict) -> np.ndarray:
    emb_score = float(candidate["emb_score"] or 0.0)
    bm25_score = float(candidate["bm25_score"] or 0.0)
    emb_rank = candidate["emb_rank"]
    bm25_rank = candidate["bm25_rank"]
    cg_rank = candidate.get("call_graph_rank")
    emb_rank_norm = 1.0 / emb_rank if emb_rank else 0.0
    bm25_rank_norm = 1.0 / bm25_rank if bm25_rank else 0.0
    cg_rank_norm = 1.0 / cg_rank if cg_rank else 0.0
    return np.array([
        emb_score,
        bm25_score,
        emb_rank_norm,
        bm25_rank_norm,
        cg_rank_norm,
        float(bool(candidate["in_call_graph"])),
        float(bool(candidate["name_in_query"])),
        float(bool(candidate["starts_with_underscore"])),
        float(bool(candidate["same_file_as_entry"])),
        1.0,  # bias
    ], dtype=np.float64)


def _build_matrices(examples: list[dict]) -> tuple[np.ndarray, np.ndarray]:
    rows_X, rows_y = [], []
    for ex in examples:
        for c in ex["pool"]:
            rows_X.append(_feature_vector(c))
            rows_y.append(float(c["is_true_B"]))
    return np.array(rows_X), np.array(rows_y)


# ── normalisation ──────────────────────────────────────────────────────────────

def _fit_scaler(X: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    means = X[:, _CONTINUOUS_IDX].mean(axis=0)
    stds = X[:, _CONTINUOUS_IDX].std(axis=0) + 1e-8
    return means, stds


def _apply_scaler(X: np.ndarray, means: np.ndarray, stds: np.ndarray) -> np.ndarray:
    X_norm = X.copy()
    X_norm[:, _CONTINUOUS_IDX] = (X[:, _CONTINUOUS_IDX] - means) / stds
    return X_norm


# ── logistic regression ────────────────────────────────────────────────────────

def _sigmoid(z: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(z, -500.0, 500.0)))


def _loss_and_grad(
    w: np.ndarray,
    X: np.ndarray,
    y: np.ndarray,
    reg: float,
) -> tuple[float, np.ndarray]:
    scores = X @ w
    probs = _sigmoid(scores)
    eps = 1e-10
    loss = -np.sum(y * np.log(probs + eps) + (1 - y) * np.log(1 - probs + eps))
    # L2 on all weights except bias (last element)
    loss += 0.5 * reg * float(np.dot(w[:-1], w[:-1]))
    err = probs - y
    grad = X.T @ err
    grad[:-1] += reg * w[:-1]
    return float(loss), grad


def _train(X: np.ndarray, y: np.ndarray, reg: float = 0.5) -> np.ndarray:
    w0 = np.zeros(X.shape[1])
    result = minimize(
        fun=lambda w: _loss_and_grad(w, X, y, reg),
        x0=w0,
        method="L-BFGS-B",
        jac=True,
        options={"maxiter": 500, "ftol": 1e-9},
    )
    return result.x


# ── ranking helpers ────────────────────────────────────────────────────────────

def _rank_by_weight(candidates: list[dict], w: np.ndarray,
                    means: np.ndarray, stds: np.ndarray) -> list[str]:
    X = np.array([_feature_vector(c) for c in candidates])
    X_norm = _apply_scaler(X, means, stds)
    scores = X_norm @ w
    order = np.argsort(-scores)
    return [candidates[i]["function_name"] for i in order]


def _rank_embedding_from_pool(pool: list[dict]) -> list[str]:
    inf = float("inf")
    return [c["function_name"] for c in sorted(
        pool, key=lambda c: (c["emb_rank"] if c["emb_rank"] is not None else inf)
    )]


def _rank_bm25_from_pool(pool: list[dict]) -> list[str]:
    inf = float("inf")
    return [c["function_name"] for c in sorted(
        pool, key=lambda c: (c["bm25_rank"] if c["bm25_rank"] is not None else inf)
    )]


def _rank_call_graph_from_pool(pool: list[dict]) -> list[str]:
    inf = float("inf")
    cg = sorted([c for c in pool if c["in_call_graph"]],
                key=lambda c: (c["bm25_rank"] if c["bm25_rank"] else inf))
    non_cg = sorted([c for c in pool if not c["in_call_graph"]],
                    key=lambda c: (c["bm25_rank"] if c["bm25_rank"] else inf))
    return [c["function_name"] for c in cg + non_cg]


# ── metrics ────────────────────────────────────────────────────────────────────

def _metrics(true_b: str, ranked: list[str]) -> dict:
    if true_b not in ranked:
        return {"top1": 0, "top3": 0, "top5": 0, "rr": 0.0, "rank": None}
    rank = ranked.index(true_b) + 1
    return {
        "top1": int(rank == 1),
        "top3": int(rank <= 3),
        "top5": int(rank <= 5),
        "rr": 1.0 / rank,
        "rank": rank,
    }


# ── LOO-CV ─────────────────────────────────────────────────────────────────────

def _loo_cv(examples: list[dict], reg: float = 0.5) -> list[dict]:
    results = []
    for i, held_out in enumerate(examples):
        train_exs = [ex for j, ex in enumerate(examples) if j != i]

        X_train, y_train = _build_matrices(train_exs)
        means, stds = _fit_scaler(X_train)
        X_train_norm = _apply_scaler(X_train, means, stds)

        w = _train(X_train_norm, y_train, reg=reg)

        pool = held_out["pool"]
        true_b = held_out["true_B"]

        ranked_learned = _rank_by_weight(pool, w, means, stds)
        ranked_emb = _rank_embedding_from_pool(pool)
        ranked_bm25 = _rank_bm25_from_pool(pool)
        ranked_cg = _rank_call_graph_from_pool(pool)

        results.append({
            "case_id": held_out["case_id"],
            "true_B": true_b,
            "true_B_in_pool": held_out["true_B_in_pool"],
            "pool_size": held_out["pool_size"],
            "learned": _metrics(true_b, ranked_learned),
            "embedding": _metrics(true_b, ranked_emb),
            "bm25": _metrics(true_b, ranked_bm25),
            "call_graph": _metrics(true_b, ranked_cg),
            "learned_selected": ranked_learned[0] if ranked_learned else None,
            "w_feature_importances": dict(zip(FEATURE_NAMES, w.tolist())),
        })
    return results


# ── aggregate ──────────────────────────────────────────────────────────────────

def _aggregate(results: list[dict], key: str, n_pool: int) -> dict:
    vals = [r[key] for r in results if r["true_B_in_pool"]]
    if not vals:
        return {"top1": "0/0", "top3": "0/0", "top5": "0/0", "mrr": 0.0}
    return {
        "top1": f"{sum(v['top1'] for v in vals)}/{n_pool}",
        "top3": f"{sum(v['top3'] for v in vals)}/{n_pool}",
        "top5": f"{sum(v['top5'] for v in vals)}/{n_pool}",
        "mrr": round(sum(v["rr"] for v in vals) / len(vals), 3),
        "_top1_int": sum(v["top1"] for v in vals),
    }


# ── main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--training", default=str(DEFAULT_TRAINING))
    parser.add_argument("--reg", type=float, default=0.5,
                        help="L2 regularization coefficient")
    args = parser.parse_args()

    training_path = Path(args.training)
    if not training_path.exists():
        print(f"ERROR: training file not found: {training_path}")
        print("Run localizer_bench.py first to generate localizer_training.jsonl")
        sys.exit(1)

    examples = []
    with training_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                examples.append(json.loads(line))

    n = len(examples)
    print(f"Loaded {n} training examples from {training_path.name}")

    if n < 2:
        print("ERROR: need ≥2 examples for LOO-CV")
        sys.exit(1)

    print(f"Running LOO-CV (n={n}, reg={args.reg})...")
    results = _loo_cv(examples, reg=args.reg)

    n_pool = sum(1 for r in results if r["true_B_in_pool"])

    # Per-case output
    print()
    hdr = f"  {'case_id':<14} {'learned':>8} {'emb':>8} {'bm25':>8} {'call_graph':>12}  B"
    print(hdr)
    print("  " + "-" * 68)
    for r in results:
        def fmt(m):
            if m["rank"] is None:
                return "MISS    "
            return f"@{m['rank']} {'Y' if m['top1'] else ('~' if m['top3'] else 'N'):1}  "
        print(
            f"  {r['case_id']:<14} "
            f"{fmt(r['learned'])}"
            f"{fmt(r['embedding'])}"
            f"{fmt(r['bm25'])}"
            f"{'@'+str(r['call_graph']['rank']) if r['call_graph']['rank'] else 'MISS':>10}  "
            f"{r['true_B']}"
        )

    # Aggregates
    strategies = ["learned", "embedding", "bm25", "call_graph"]
    aggs = {s: _aggregate(results, s, n_pool) for s in strategies}

    sep = "=" * 65
    print(f"\n{sep}")
    print(f"LOO-CV SUMMARY  n={n_pool} cases with B in pool")
    print(sep)
    print(f"{'Strategy':<16} {'top-1':>8} {'top-3':>8} {'top-5':>8} {'MRR':>8}")
    print("-" * 65)
    for s in strategies:
        a = aggs[s]
        print(f"{s:<16} {a['top1']:>8} {a['top3']:>8} {a['top5']:>8} {a['mrr']:>8.3f}")
    print(sep)

    # §S4 verdict
    delta = aggs["learned"]["_top1_int"] - aggs["embedding"]["_top1_int"]
    print(f"\nDelta top-1 (learned - embedding): {delta:+d}/{n_pool}")
    print(f"S4 precommit: need >=15 pp on >=20 held-out cases before claiming self-learning.")
    if n_pool < 20:
        verdict = "INSUFFICIENT_DATA"
        print(f"INSUFFICIENT DATA: {n_pool}/20 cases. Verdict deferred.")
    elif delta / n_pool >= 0.15:
        verdict = "GREEN"
        print(f"GREEN: {delta}/{n_pool} exceeds 15 pp threshold.")
    else:
        verdict = "RED"
        print(f"RED: {delta}/{n_pool} does not reach 15 pp threshold.")

    # Feature importances (average across LOO folds)
    all_w = [r["w_feature_importances"] for r in results]
    avg_w = {name: round(sum(d[name] for d in all_w) / len(all_w), 4)
             for name in FEATURE_NAMES}
    print(f"\nAvg feature weights (LOO mean):")
    for name, val in sorted(avg_w.items(), key=lambda t: abs(t[1]), reverse=True):
        bar = "+" * min(int(abs(val) * 5), 20) if val >= 0 else "-" * min(int(abs(val) * 5), 20)
        print(f"  {name:<28} {val:+.4f}  {bar}")

    # Save
    out = {
        "n_cases": n,
        "n_with_B_in_pool": n_pool,
        "reg": args.reg,
        "loo_cv_cases": results,
        "aggregate": {s: {k: v for k, v in aggs[s].items() if not k.startswith("_")} for s in strategies},
        "delta_top1_learned_vs_embedding": delta,
        "s4_threshold_pp": 15,
        "s4_min_cases": 20,
        "s4_verdict": verdict,
        "avg_feature_weights": avg_w,
    }
    RESULTS_OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"\nResults: {RESULTS_OUT}")


if __name__ == "__main__":
    main()
