"""
testfix.arm_b2
--------------
ARM_B2: BM25 test-source retrieval arm.

Query  = test source + error message + test name + pytest E-lines (NO function A source).
Corpus = all 266 top-level functions in app/, indexed by name + body.
Top-5  = retrieved candidate helpers, shown to model alongside function A.

Comparison:
  ARM_A  : 0/7 = 0.0%  (function A source only)
  ARM_B  : 7/7 = 100%  (oracle call-graph expansion)
  ARM_B2 : ???         (BM25 test-query top-5 from 266-function corpus)

Pre-committed interpretation:
  7/7       BM25 sufficient on this repo; call-graph oracle redundant at current scale.
  >=5/7     BM25 viable; needs scaling audit at 500+ function corpus.
  <5/7      Retrieval quality is the bottleneck; call-graph is load-bearing.

Diagnostic output:
  - Corpus size and random recall@5 baseline (5/N)
  - Per-case: rank of correct helper B in BM25 results (retrieval recall)
  - Per-case: end-to-end pass/fail (fix quality given the retrieved candidates)
  - Aggregate: in_top_1, in_top_3, in_top_5 counts vs pass rate

Usage (from openrent-agent/):
    python testfix/arm_b2.py [--attempts N] [--model MODEL] [--retrieval-only]
"""

import argparse
import ast
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _import_all():
    sys.path.insert(0, str(ROOT))
    from testfix.extractor import _extract_function_source, extract_failure
    from testfix.verifier import verify_fix, _patched
    from testfix.retriever_bm25 import build_corpus, build_query
    return _extract_function_source, extract_failure, verify_fix, _patched, build_corpus, build_query


def _parse_def_name(source: str) -> str | None:
    try:
        tree = ast.parse(source.strip())
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return node.name
    except SyntaxError:
        pass
    m = re.match(r"(?:async\s+)?def\s+(\w+)\s*\(", source.strip())
    return m.group(1) if m else None


def _build_prompt(
    test_source: str,
    entry_source: str,
    candidates: list[dict],
    error_message: str,
) -> str:
    cand_section = ""
    if candidates:
        block = ""
        for c in candidates:
            block += f"\n--- Candidate {c['rank']}: {c['function_name']} ({c['file_path']}) ---\n{c['source']}\n"
        cand_section = f"\nTOP-5 CANDIDATE HELPER FUNCTIONS (retrieved by lexical search — one may contain the bug, or the bug may be in the entry-point itself):\n{block}"

    return (
        "You are fixing a Python bug. A test is failing. The test calls the entry-point "
        "function shown below. The bug may be inside the entry-point OR in one of the "
        "retrieved candidate helpers.\n\n"
        f"FAILING TEST:\n{test_source}\n\n"
        f"ENTRY-POINT FUNCTION (the function the test calls directly):\n{entry_source}\n"
        f"{cand_section}\n"
        f"TEST ERROR:\n{error_message}\n\n"
        "Return ONLY the corrected function — no explanation, no markdown, no backticks.\n"
        "The function must start with `def` or `async def` on the first line."
    )


def _propose_fix(prompt: str, model: str) -> tuple[str | None, float]:
    from openai import OpenAI
    from app.config import settings

    client = OpenAI(api_key=settings.OPENAI_API_KEY, timeout=30.0)
    t0 = time.perf_counter()
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
        )
        latency_ms = (time.perf_counter() - t0) * 1000
        content = (response.choices[0].message.content or "").strip()
        if content.startswith("```"):
            lines = content.splitlines()
            content = "\n".join(
                line for line in lines if not line.strip().startswith("```")
            ).strip()
        return content, latency_ms
    except Exception:
        latency_ms = (time.perf_counter() - t0) * 1000
        return None, latency_ms


def _apply_mutation(function_source: str, original_snippet: str, mutated_snippet: str) -> str | None:
    if original_snippet not in function_source:
        return None
    return function_source.replace(original_snippet, mutated_snippet, 1)


def _replace_in_file(file_source: str, original_func: str, new_func: str) -> str:
    if original_func not in file_source:
        return file_source
    return file_source.replace(original_func, new_func, 1)


def run_case_b2(
    case, seed_map,
    extract_failure, verify_fix, _extract_function_source, _patched,
    bm25_index, build_query,
    max_attempts: int, model: str,
) -> dict:
    case_id = case["case_id"]
    test_id = case["test_id"]
    target_file = case["target_file"]   # B's file
    func_name = case["target_function"] # B (the broken helper)
    target_path = ROOT / target_file

    seed = seed_map.get(case_id)
    if not seed:
        return {"case_id": case_id, "error": "no seed definition",
                "attempts": [], "retrieval": {}, "passed": False}

    original_func_source = _extract_function_source(target_path, func_name)
    if not original_func_source:
        return {"case_id": case_id, "error": "could not extract function",
                "attempts": [], "retrieval": {}, "passed": False}

    mutated_func_source = _apply_mutation(
        original_func_source, seed["original_snippet"], seed["mutated_snippet"]
    )
    if mutated_func_source is None:
        return {"case_id": case_id, "error": "snippet not found",
                "attempts": [], "retrieval": {}, "passed": False}

    original_file_source = target_path.read_text(encoding="utf-8")
    mutated_file_source = _replace_in_file(
        original_file_source, original_func_source, mutated_func_source
    )

    # Extract failure context once (same across attempts)
    with _patched(target_path, mutated_file_source, original_file_source):
        failure_ctx = extract_failure(test_id)

    if not failure_ctx:
        return {"case_id": case_id, "error": "test passed on mutated code",
                "attempts": [], "retrieval": {}, "passed": False}

    entry_source = failure_ctx["target_source"] or mutated_func_source
    error_msg = failure_ctx["error_message"] or ""
    test_src = failure_ctx["test_source"] or ""
    pytest_out = failure_ctx.get("pytest_output", "")
    entry_func_name = failure_ctx.get("target_function")  # function A's name

    # Build BM25 query from test-side signals only — no function A source
    test_name = test_id.rsplit("::", 1)[-1] if "::" in test_id else ""
    query_text = build_query(test_src, error_msg, test_name, pytest_out)
    # Exclude function A from candidates (it's already shown separately in the prompt)
    candidates = bm25_index.query(query_text, top_k=5, exclude_function=entry_func_name)

    # Retrieval diagnostic: rank of correct helper B
    correct_rank: int | None = None
    for c in candidates:
        if c["function_name"] == func_name:
            correct_rank = c["rank"]
            break

    retrieval = {
        "query_tokens_preview": " ".join(
            t for t in query_text.split() if len(t) >= 3
        )[:140],
        "candidates": [
            {"rank": c["rank"], "score": c["score"],
             "function_name": c["function_name"], "file_path": c["file_path"]}
            for c in candidates
        ],
        "correct_function": func_name,
        "correct_rank": correct_rank,
        "correct_in_top_1": correct_rank == 1,
        "correct_in_top_3": correct_rank is not None and correct_rank <= 3,
        "correct_in_top_5": correct_rank is not None and correct_rank <= 5,
    }

    # Fix loop (skipped if max_attempts == 0 for retrieval-only mode)
    attempts: list[dict] = []
    passed_on_attempt: int | None = None
    cand_map = {c["function_name"]: c["file_path"] for c in candidates}

    for attempt_num in range(1, max_attempts + 1):
        prompt = _build_prompt(test_src, entry_source, candidates, error_msg)
        proposed, latency_ms = _propose_fix(prompt, model)

        if not proposed:
            attempts.append({
                "attempt": attempt_num, "error": "proposer returned empty",
                "latency_ms": round(latency_ms),
            })
            continue

        proposed_name = _parse_def_name(proposed)

        # Determine target file/func for verification
        if proposed_name and proposed_name in cand_map:
            fix_file, fix_func = cand_map[proposed_name], proposed_name
        elif proposed_name and proposed_name == entry_func_name:
            fix_file = failure_ctx.get("target_file") or target_file
            fix_func = proposed_name
        else:
            fix_file, fix_func = target_file, func_name

        # Re-apply the mutation during verification so the test only passes
        # if the proposed fix actually undoes the bug (not just because the
        # mutation was already reverted when we're outside _patched).
        # If the model proposes function A on a case where B is broken,
        # target_path still has the mutation → test still fails correctly.
        with _patched(target_path, mutated_file_source, original_file_source):
            verify_result = verify_fix(test_id, proposed, fix_file, fix_func)

        attempts.append({
            "attempt": attempt_num,
            "passed": verify_result["passed"],
            "proposed_function": proposed_name,
            "fix_function": fix_func,
            "fix_file": fix_file,
            "latency_ms": round(latency_ms),
            "verify_error": verify_result.get("error"),
        })

        if verify_result["passed"]:
            passed_on_attempt = attempt_num
            break

    return {
        "case_id": case_id,
        "failure_mode": case.get("failure_mode"),
        "source_type": case.get("source_type"),
        "triage_ground_truth": case.get("triage_ground_truth"),
        "target_function": func_name,
        "target_file": target_file,
        "passed": passed_on_attempt is not None,
        "passed_on_attempt": passed_on_attempt,
        "retrieval": retrieval,
        "attempts": attempts,
        "error": None,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--model", default="gpt-4.1-mini")
    parser.add_argument("--baseline", default="testfix/baseline_cross_function.jsonl")
    parser.add_argument("--seeds-module", default="testfix.seeds_cross")
    parser.add_argument("--output", default="testfix/arm_b2_results.json")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--retrieval-only", action="store_true",
                        help="Show retrieval rankings without calling the model")
    args = parser.parse_args()

    _extract_function_source, extract_failure, verify_fix, _patched, build_corpus, build_query = _import_all()

    print("Building BM25 corpus from app/...", end=" ", flush=True)
    bm25_index = build_corpus()
    random_recall5 = 5 / bm25_index.size if bm25_index.size else 0
    print(f"{bm25_index.size} functions. Random recall@5 baseline: {random_recall5:.1%}")

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
    effective_attempts = 0 if args.retrieval_only else args.attempts

    print(f"ARM_B2: {len(cases)} cases, model={args.model}"
          + (" [retrieval-only]" if args.retrieval_only else f", max_attempts={args.attempts}"))
    if args.dry_run:
        for c in cases:
            print(f"  {c['case_id']} -> {c['target_function']} ({c['target_file']})")
        return

    print()
    results = []
    for i, case in enumerate(cases):
        func_name = case["target_function"]
        print(f"[{i+1}/{len(cases)}] {case['case_id']} (B={func_name})...", end=" ", flush=True)

        result = run_case_b2(
            case, seed_map,
            extract_failure, verify_fix, _extract_function_source, _patched,
            bm25_index, build_query,
            max_attempts=effective_attempts, model=args.model,
        )

        ret = result["retrieval"]
        rank_str = f"B@{ret.get('correct_rank', 'MISS')}"
        cand_names = [c["function_name"] for c in ret.get("candidates", [])]

        if args.retrieval_only:
            print(f"{rank_str}  top5={cand_names}")
        else:
            status = f"PASS(a{result['passed_on_attempt']})" if result["passed"] else "FAIL"
            latencies = [a["latency_ms"] for a in result["attempts"] if "latency_ms" in a]
            med = sorted(latencies)[len(latencies) // 2] if latencies else 0
            print(f"{status}  {rank_str}  top5={cand_names}  (~{med}ms)")

        results.append(result)

    # ── aggregate metrics ──────────────────────────────────────────────────────
    total = len(results)
    in_top1 = sum(1 for r in results if r["retrieval"].get("correct_in_top_1"))
    in_top3 = sum(1 for r in results if r["retrieval"].get("correct_in_top_3"))
    in_top5 = sum(1 for r in results if r["retrieval"].get("correct_in_top_5"))

    first_pass = sum(1 for r in results if r.get("passed_on_attempt") == 1)
    any_pass = sum(1 for r in results if r.get("passed"))
    all_latencies = [
        a["latency_ms"] for r in results
        for a in r.get("attempts", []) if "latency_ms" in a
    ]
    median_lat = sorted(all_latencies)[len(all_latencies) // 2] if all_latencies else 0

    by_mode = {}
    for r in results:
        mode = r.get("failure_mode", "unknown")
        by_mode.setdefault(mode, {"passed": 0, "total": 0})
        by_mode[mode]["total"] += 1
        if r.get("passed"):
            by_mode[mode]["passed"] += 1

    summary = {
        "corpus_size": bm25_index.size,
        "random_recall_at_5": round(random_recall5, 4),
        "retrieval_recall": {
            "in_top_1": f"{in_top1}/{total}",
            "in_top_3": f"{in_top3}/{total}",
            "in_top_5": f"{in_top5}/{total}",
        },
        "first_attempt_pass_rate": round(first_pass / total, 3) if (total and not args.retrieval_only) else None,
        "pass_rate_after_n_attempts": round(any_pass / total, 3) if (total and not args.retrieval_only) else None,
        "max_attempts": args.attempts,
        "median_latency_ms": median_lat,
        "arm_a_baseline": "0/7 = 0.0%",
        "arm_b_oracle": "7/7 = 100.0%",
        "by_failure_mode": by_mode,
        "cases": results,
    }

    if not args.retrieval_only:
        out_path = ROOT / args.output
        out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    sep = "-" * 58
    print(f"\n{sep}")
    print(f"ARM_B2 RESULTS  model={args.model}  corpus={bm25_index.size} fns")
    print(sep)
    print(f"  ARM_A  (no helpers)       : 0/7  =  0.0%")
    print(f"  ARM_B  (oracle call-graph): 7/7  = 100.0%")
    if not args.retrieval_only:
        print(f"  ARM_B2 first-attempt      : {first_pass}/{total}  = {first_pass/total:.1%}")
        print(f"  ARM_B2 after-{args.attempts}-attempts   : {any_pass}/{total}  = {any_pass/total:.1%}")
        print(f"  median latency            : {median_lat} ms")
    print(f"\n  Corpus: {bm25_index.size} fns  |  random recall@5 = {random_recall5:.1%}")
    print(f"\n  Retrieval recall (B in top-K of 266):")
    print(f"    top-1 : {in_top1}/{total} = {in_top1/total:.1%}")
    print(f"    top-3 : {in_top3}/{total} = {in_top3/total:.1%}")
    print(f"    top-5 : {in_top5}/{total} = {in_top5/total:.1%}")
    print(f"\n  Per-case (B=broken helper  rank=BM25 position  {'pass=end-to-end' if not args.retrieval_only else 'retrieval-only'}):")
    for r in results:
        ret = r["retrieval"]
        rk = ret.get("correct_rank")
        rank_str = f"@{rk}" if rk else ">5"
        cands = [c["function_name"] for c in ret.get("candidates", [])]
        if args.retrieval_only:
            print(f"    {r['case_id']}  B={r['target_function']:<28} rank={rank_str:<3}  top5={cands}")
        else:
            passed_str = "PASS" if r.get("passed") else "FAIL"
            print(f"    {r['case_id']}  B={r['target_function']:<28} rank={rank_str:<3}  {passed_str}  top5={cands}")
    if not args.retrieval_only:
        print(f"\n  By failure mode:")
        for mode, counts in sorted(by_mode.items()):
            rate = counts["passed"] / counts["total"] if counts["total"] else 0
            print(f"    {mode:<45} {counts['passed']}/{counts['total']} ({rate:.0%})")
        print(f"\nFull results: {ROOT / args.output}")


if __name__ == "__main__":
    main()
