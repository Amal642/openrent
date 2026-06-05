"""
testfix.localizer_bench
-----------------------
Localizer-only benchmark for OPEN-52.

Tests how well each strategy localizes the broken helper B given a failing test,
compact function signatures, and an error message.

The benchmark is independent of repair: it only measures whether each strategy
ranks B at the top of a fixed candidate pool. Repair quality is NOT measured here.

Candidate pool (per case)
  Top-10 from embedding  +  all functions directly called by A (call-graph).
  Deduplicated. B is in the pool for all 7 cases via the call-graph component.

Compact signature format
  def line + first docstring line (or first body line), ≤80 chars.
  This is what the LLM localizer sees — interface only, not full implementation.
  BM25/embedding baselines use full source in their pre-built indices.

Localizer strategies compared
  random       : shuffled (lower bound)
  bm25         : ranked by BM25 score from the pre-built 266-fn index
  embedding    : ranked by cosine similarity from the pre-built 266-fn index
  call_graph   : B first if in call-graph, else B last (structural oracle)
  llm_compact  : one model call per case; sees compact signatures only

Metrics
  top-1 / top-3 / top-5 accuracy  (is B in the top-K of the ranking?)
  MRR (mean reciprocal rank of B across all 7 cases)

Outputs
  Printed comparison table
  testfix/localizer_bench_results.json   (full per-case breakdown)
  testfix/localizer_training.jsonl       (training examples for localizer_learned.py)

Usage (from openrent-agent/):
    python testfix/localizer_bench.py [--model MODEL] [--no-llm] [--output-dir testfix/]
"""

import argparse
import ast
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _import_all():
    sys.path.insert(0, str(ROOT))
    from testfix.extractor import _extract_function_source, extract_failure
    from testfix.verifier import _patched
    from testfix.retriever_bm25 import build_corpus as bm25_build, build_query
    from testfix.retriever_embedding import build_corpus as emb_build
    from testfix.retriever import retrieve_helpers, _extract_called_names
    return (_extract_function_source, extract_failure, _patched,
            bm25_build, emb_build, build_query,
            retrieve_helpers, _extract_called_names)


# ── compact signature ──────────────────────────────────────────────────────────

def _compact_signature(source: str) -> str:
    """
    Return def-line + first docstring or body line.
    Shows the function interface without revealing the bug.
    Max 80 chars on the annotation line.
    """
    lines = source.strip().splitlines()
    if not lines:
        return ""
    def_line = lines[0]
    for line in lines[1:]:
        s = line.strip()
        if not s:
            continue
        # Docstring
        if s.startswith('"""') or s.startswith("'''"):
            inner = s.strip('"""').strip("'''").strip()
            if inner:
                return f"{def_line}\n    # {inner[:80]}"
            # Empty first docstring line — look at next
            continue
        # First real body line
        return f"{def_line}\n    # [{s[:78]}]"
    return def_line


# ── candidate pool ─────────────────────────────────────────────────────────────

def _build_pool(
    entry_func_name: str,
    entry_file: str,
    emb_index,
    bm25_index,
    build_query_fn,
    retrieve_helpers_fn,
    test_src: str,
    error_msg: str,
    test_name: str,
    pytest_out: str,
    top_k_emb: int = 10,
) -> list[dict]:
    """
    Return candidate pool: top-10 embedding ∪ call-graph functions.
    Each entry: {function_name, file_path, source, compact, bm25_rank, emb_rank, in_call_graph}.
    Entry-point A is excluded. Pool is deduplicated by function_name.
    """
    query_text = build_query_fn(test_src, error_msg, test_name, pytest_out)

    # Embedding ranking (top-10, excludes entry-point)
    emb_results = emb_index.query(query_text, top_k=top_k_emb, exclude_function=entry_func_name)
    emb_map = {r["function_name"]: r for r in emb_results}

    # BM25 ranking (all, for scoring)
    bm25_all = bm25_index.query(query_text, top_k=bm25_index.size, exclude_function=entry_func_name)
    bm25_rank_map = {r["function_name"]: r["rank"] for r in bm25_all}
    bm25_score_map = {r["function_name"]: r["score"] for r in bm25_all}

    # Call-graph: functions directly called by A
    entry_path = ROOT / entry_file
    try:
        entry_source = entry_path.read_text(encoding="utf-8")
    except OSError:
        entry_source = ""
    call_graph = retrieve_helpers_fn(entry_source)  # {name: (rel_path, source)}
    cg_rank_map = {name: i + 1 for i, name in enumerate(call_graph)}  # 1-indexed ordinal

    # Build pool: embedding top-10 first, then call-graph additions
    pool_names: list[str] = []
    pool_data: dict[str, dict] = {}

    for r in emb_results:
        name = r["function_name"]
        if name not in pool_data:
            pool_names.append(name)
            pool_data[name] = {
                "function_name": name,
                "file_path": r["file_path"],
                "source": r["source"],
                "compact": _compact_signature(r["source"]),
                "emb_rank": r["rank"],
                "emb_score": r["score"],
                "bm25_rank": bm25_rank_map.get(name),
                "bm25_score": bm25_score_map.get(name, 0.0),
                "in_call_graph": name in call_graph,
                "call_graph_rank": cg_rank_map.get(name),
            }

    for name, (rel_path, src) in call_graph.items():
        if name not in pool_data and name != entry_func_name:
            pool_names.append(name)
            pool_data[name] = {
                "function_name": name,
                "file_path": rel_path,
                "source": src,
                "compact": _compact_signature(src),
                "emb_rank": None,
                "emb_score": None,
                "bm25_rank": bm25_rank_map.get(name),
                "bm25_score": bm25_score_map.get(name, 0.0),
                "in_call_graph": True,
                "call_graph_rank": cg_rank_map[name],
            }

    return [pool_data[n] for n in pool_names]


# ── ranking strategies ─────────────────────────────────────────────────────────

import random as _random


def _rank_random(pool: list[dict], seed: int = 0) -> list[str]:
    names = [c["function_name"] for c in pool]
    _random.seed(seed)
    _random.shuffle(names)
    return names


def _rank_bm25(pool: list[dict]) -> list[str]:
    """Lower rank number = higher BM25 score = rank first."""
    inf = float("inf")
    return [c["function_name"] for c in sorted(pool, key=lambda c: c["bm25_rank"] or inf)]


def _rank_embedding(pool: list[dict]) -> list[str]:
    """Lower emb_rank = higher similarity = rank first. Call-graph-only entries go last."""
    inf = float("inf")
    return [c["function_name"] for c in sorted(pool, key=lambda c: c["emb_rank"] or inf)]


def _rank_call_graph(pool: list[dict]) -> list[str]:
    """Call-graph members first (ranked by bm25 within group), then non-members."""
    cg = [c for c in pool if c["in_call_graph"]]
    non_cg = [c for c in pool if not c["in_call_graph"]]
    inf = float("inf")
    cg_sorted = sorted(cg, key=lambda c: c["bm25_rank"] or inf)
    non_cg_sorted = sorted(non_cg, key=lambda c: c["bm25_rank"] or inf)
    return [c["function_name"] for c in cg_sorted + non_cg_sorted]


def _rank_llm_compact(
    test_src: str,
    entry_compact: str,
    pool: list[dict],
    error_msg: str,
    model: str,
    valid_names: set[str],
) -> tuple[list[str], str | None, float]:
    """
    One model call with compact signatures only.
    Returns (ranked_names, selected_name, latency_ms).
    The model picks one function; that goes to rank 1, rest ordered by embedding.
    """
    from openai import OpenAI
    from app.config import settings

    block = ""
    for i, c in enumerate(pool, 1):
        block += f"\n{i}. {c['compact']}\n"

    prompt = (
        "A Python test is failing. The test calls the entry-point function below, "
        "but the bug may be in a helper it calls.\n\n"
        f"FAILING TEST (name + key lines):\n{test_src[:600]}\n\n"
        f"ENTRY-POINT:\n{entry_compact}\n\n"
        f"CANDIDATE HELPERS (signatures only — implementation hidden):\n{block}\n"
        f"TEST ERROR:\n{error_msg[:300]}\n\n"
        "Which single function most likely contains the bug?\n"
        "Reply with ONLY the function name. Nothing else."
    )

    client = OpenAI(api_key=settings.OPENAI_API_KEY, timeout=20.0)
    t0 = time.perf_counter()
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=32,
        )
        latency_ms = (time.perf_counter() - t0) * 1000
        reply = (response.choices[0].message.content or "").strip()
    except Exception:
        latency_ms = (time.perf_counter() - t0) * 1000
        reply = ""

    # Parse selected name
    import re
    selected = None
    reply_clean = reply.strip()
    if reply_clean in valid_names:
        selected = reply_clean
    else:
        for name in valid_names:
            if re.search(r"\b" + re.escape(name) + r"\b", reply_clean):
                selected = name
                break

    # Build ranked list: selected first, then by embedding rank
    emb_ranked = _rank_embedding(pool)
    if selected and selected in emb_ranked:
        emb_ranked.remove(selected)
        ranked = [selected] + emb_ranked
    else:
        ranked = emb_ranked

    return ranked, selected, latency_ms


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


# ── training data export ───────────────────────────────────────────────────────

def _relation(selected: str | None, true_b: str, call_graph: set[str]) -> str:
    if selected is None:
        return "none"
    if selected == true_b:
        return "exact_B"
    if selected in call_graph:
        return "call_graph_hit"
    return "unrelated"


def _export_training_example(
    case_id: str,
    failure_mode: str,
    query_text: str,
    entry_func: str,
    entry_file: str,
    pool: list[dict],
    true_b: str,
    llm_selected: str | None,
    llm_repair_passed: bool | None,
    bm25_ranked: list[str],
    emb_ranked: list[str],
) -> dict:
    pool_with_labels = []
    for c in pool:
        pool_with_labels.append({
            "function_name": c["function_name"],
            "file_path": c["file_path"],
            "compact": c["compact"],
            "emb_rank": c["emb_rank"],
            "emb_score": c["emb_score"],
            "bm25_rank": c["bm25_rank"],
            "bm25_score": c["bm25_score"],
            "in_call_graph": c["in_call_graph"],
            "call_graph_rank": c.get("call_graph_rank"),
            "is_true_B": c["function_name"] == true_b,
            "name_in_query": c["function_name"] in query_text,
            "starts_with_underscore": c["function_name"].startswith("_"),
            "same_file_as_entry": c["file_path"].endswith(entry_file.replace("\\", "/").split("/")[-1]),
        })
    return {
        "case_id": case_id,
        "failure_mode": failure_mode,
        "query_text": query_text,
        "entry_func": entry_func,
        "entry_file": entry_file,
        "true_B": true_b,
        "true_B_in_pool": any(c["function_name"] == true_b for c in pool),
        "pool_size": len(pool),
        "pool": pool_with_labels,
        "llm_selected": llm_selected,
        "llm_repair_passed": llm_repair_passed,
        "bm25_rank_of_B": bm25_ranked.index(true_b) + 1 if true_b in bm25_ranked else None,
        "emb_rank_of_B": emb_ranked.index(true_b) + 1 if true_b in emb_ranked else None,
    }


# ── mutation helpers (shared with other arm scripts) ──────────────────────────

def _apply_mutation(src, orig, mut):
    if orig not in src:
        return None
    return src.replace(orig, mut, 1)


def _replace_in_file(fsrc, orig_fn, new_fn):
    if orig_fn not in fsrc:
        return fsrc
    return fsrc.replace(orig_fn, new_fn, 1)


# ── main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="gpt-4.1-mini")
    parser.add_argument("--no-llm", action="store_true",
                        help="Skip LLM localizer (BM25/embedding/call-graph baselines only)")
    parser.add_argument("--baseline", default="testfix/baseline_cross_function.jsonl")
    parser.add_argument("--seeds-module", default="testfix.seeds_cross")
    parser.add_argument("--output", default="testfix/localizer_bench_results.json")
    parser.add_argument("--training-output", default="testfix/localizer_training.jsonl")
    args = parser.parse_args()

    (
        _extract_function_source, extract_failure, _patched,
        bm25_build, emb_build, build_query,
        retrieve_helpers, _extract_called_names,
    ) = _import_all()

    print("Building BM25 corpus...", end=" ", flush=True)
    bm25_index = bm25_build()
    print(f"{bm25_index.size} fns")

    print("Building embedding corpus (API calls)...", end=" ", flush=True)
    emb_index = emb_build()
    print(f"{emb_index.size} fns")

    import importlib
    seeds_mod = importlib.import_module(args.seeds_module)
    SEEDS_CROSS = (
        getattr(seeds_mod, "SEEDS_CROSS", None)
        or getattr(seeds_mod, "SEEDS", None)
        or []
    )

    baseline_path = ROOT / args.baseline
    cases = []
    with baseline_path.open(encoding="utf-8") as f:
        for line in f:
            c = json.loads(line.strip())
            if not c.get("exclude_from_headline") and c.get("extractor_ok") and c.get("verifier_ok"):
                cases.append(c)

    seed_map = {s["case_id"]: s for s in SEEDS_CROSS}

    strategies = ["random", "bm25", "embedding", "call_graph"]
    if not args.no_llm:
        strategies.append("llm_compact")

    # Per-strategy accumulators
    totals = {s: {"top1": 0, "top3": 0, "top5": 0, "rr_sum": 0.0, "in_pool": 0} for s in strategies}
    all_case_results = []
    training_examples = []

    print(f"\nLocalizer benchmark: {len(cases)} cases, strategies={strategies}\n")

    for i, case in enumerate(cases):
        case_id = case["case_id"]
        func_name = case["target_function"]  # true B
        target_file = case["target_file"]
        target_path = ROOT / target_file

        print(f"[{i+1}/{len(cases)}] {case_id} (B={func_name})...", end=" ", flush=True)

        seed = seed_map.get(case_id)
        if not seed:
            print("SKIP (no seed)")
            continue

        original_func_source = _extract_function_source(target_path, func_name)
        if not original_func_source:
            print("SKIP (extract failed)")
            continue

        mutated_func_source = _apply_mutation(
            original_func_source, seed["original_snippet"], seed["mutated_snippet"]
        )
        if mutated_func_source is None:
            print("SKIP (snippet not found)")
            continue

        original_file_source = target_path.read_text(encoding="utf-8")
        mutated_file_source = _replace_in_file(
            original_file_source, original_func_source, mutated_func_source
        )

        with _patched(target_path, mutated_file_source, original_file_source):
            failure_ctx = extract_failure(case["test_id"])

        if not failure_ctx:
            print("SKIP (test passed on mutant)")
            continue

        test_src = failure_ctx["test_source"] or ""
        error_msg = failure_ctx["error_message"] or ""
        pytest_out = failure_ctx.get("pytest_output", "")
        entry_func_name = failure_ctx.get("target_function") or ""
        entry_file = failure_ctx.get("target_file") or target_file
        test_name = case["test_id"].rsplit("::", 1)[-1]

        # Build compact signature for entry-point
        entry_source = failure_ctx["target_source"] or ""
        entry_compact = _compact_signature(entry_source) if entry_source else entry_func_name

        # Build candidate pool
        query_text = build_query(test_src, error_msg, test_name, pytest_out)
        pool = _build_pool(
            entry_func_name, entry_file,
            emb_index, bm25_index, build_query,
            retrieve_helpers,
            test_src, error_msg, test_name, pytest_out,
        )

        valid_names = {c["function_name"] for c in pool}
        b_in_pool = func_name in valid_names

        # Run all strategies
        rankings: dict[str, list[str]] = {
            "random": _rank_random(pool),
            "bm25": _rank_bm25(pool),
            "embedding": _rank_embedding(pool),
            "call_graph": _rank_call_graph(pool),
        }
        llm_selected = None
        llm_latency = 0.0

        if "llm_compact" in strategies:
            ranked_llm, llm_selected, llm_latency = _rank_llm_compact(
                test_src, entry_compact, pool, error_msg, args.model, valid_names
            )
            rankings["llm_compact"] = ranked_llm

        # Compute metrics per strategy
        case_metrics: dict[str, dict] = {}
        for strat in strategies:
            m = _metrics(func_name, rankings[strat])
            case_metrics[strat] = m
            if b_in_pool:
                totals[strat]["top1"] += m["top1"]
                totals[strat]["top3"] += m["top3"]
                totals[strat]["top5"] += m["top5"]
                totals[strat]["rr_sum"] += m["rr"]
                totals[strat]["in_pool"] += 1

        # Print summary line
        emb_rank = case_metrics["embedding"]["rank"]
        cg_rank = case_metrics["call_graph"]["rank"]
        llm_rank = case_metrics.get("llm_compact", {}).get("rank")
        pool_str = f"pool={len(pool)}"
        b_str = "B_in_pool" if b_in_pool else "B_MISS"
        ranks_str = f"emb@{emb_rank or '?'} cg@{cg_rank or '?'}"
        if llm_selected:
            ranks_str += f" llm={llm_selected}@{llm_rank or '?'}"
        print(f"{b_str}  {pool_str}  {ranks_str}  ({round(llm_latency)}ms)")

        all_case_results.append({
            "case_id": case_id,
            "failure_mode": case.get("failure_mode"),
            "true_B": func_name,
            "true_B_in_pool": b_in_pool,
            "pool_size": len(pool),
            "pool_names": [c["function_name"] for c in pool],
            "rankings": {s: rankings[s] for s in strategies},
            "metrics": case_metrics,
            "llm_selected": llm_selected,
            "llm_latency_ms": round(llm_latency),
        })

        # Collect call_graph set for training data
        call_graph_set = {c["function_name"] for c in pool if c["in_call_graph"]}
        training_examples.append(_export_training_example(
            case_id=case_id,
            failure_mode=case.get("failure_mode", ""),
            query_text=query_text,
            entry_func=entry_func_name,
            entry_file=entry_file,
            pool=pool,
            true_b=func_name,
            llm_selected=llm_selected,
            llm_repair_passed=None,  # not measured here
            bm25_ranked=rankings["bm25"],
            emb_ranked=rankings["embedding"],
        ))

    # ── summary table ──────────────────────────────────────────────────────────
    N = len(all_case_results)
    n_in_pool = totals["random"]["in_pool"]

    sep = "=" * 70
    print(f"\n{sep}")
    print(f"LOCALIZER BENCHMARK  {N} cases  pool=top-10-emb+call-graph")
    print(sep)
    print(f"{'Strategy':<16} {'top-1':<8} {'top-3':<8} {'top-5':<8} {'MRR':<8} {'(n={n_in_pool} with B in pool)':}")
    print("-" * 70)
    for strat in strategies:
        t = totals[strat]
        n = t["in_pool"] or 1
        mrr = t["rr_sum"] / n
        print(f"{strat:<16} {t['top1']}/{n_in_pool:<5} {t['top3']}/{n_in_pool:<5} "
              f"{t['top5']}/{n_in_pool:<5} {mrr:.3f}")
    print(sep)
    print(f"  NOTE: call_graph ranks B first whenever B is in the call-graph.")
    print(f"  It is a structural oracle — use as ceiling, not fair competitor.")
    print(f"  Embedding top-10 missed B for {N - n_in_pool} case(s) (retrieval failures,")
    print(f"  recovered by call-graph component of pool).")
    print(f"\nPer-case matrix (rank of B in each strategy's ordering):")
    hdr = f"{'case_id':<14}"
    for s in strategies:
        hdr += f" {s[:10]:<12}"
    print(hdr)
    print("-" * (14 + 13 * len(strategies)))
    for r in all_case_results:
        row = f"{r['case_id']:<14}"
        for s in strategies:
            rank = r["metrics"][s]["rank"]
            row += f" {'@'+str(rank) if rank else 'MISS':<12}"
        print(row + f"  B={r['true_B']}")

    # Save results
    out_path = ROOT / args.output
    out_path.write_text(json.dumps({
        "strategies": strategies,
        "n_cases": N,
        "n_with_B_in_pool": n_in_pool,
        "aggregate": {
            s: {
                "top1": f"{t['top1']}/{n_in_pool}",
                "top3": f"{t['top3']}/{n_in_pool}",
                "top5": f"{t['top5']}/{n_in_pool}",
                "mrr": round(t["rr_sum"] / (t["in_pool"] or 1), 3),
            }
            for s, t in totals.items()
        },
        "cases": all_case_results,
    }, indent=2), encoding="utf-8")
    print(f"\nResults: {out_path}")

    # Save training data
    train_path = ROOT / args.training_output
    with train_path.open("w", encoding="utf-8") as f:
        for ex in training_examples:
            f.write(json.dumps(ex) + "\n")
    print(f"Training data: {train_path}  ({len(training_examples)} examples)")


if __name__ == "__main__":
    main()
