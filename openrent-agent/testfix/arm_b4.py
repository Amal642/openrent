"""
testfix.arm_b4
--------------
ARM_B4: Module import-graph arm.

Candidates = ALL top-level functions in function A's module +
             ALL top-level functions from every module that A's module imports
             (1 import hop, within app/ only).

No query, no ranking — this is a structural retrieval: if B is reachable from
A's module via imports, it will appear in the candidate set.

Distinction from ARM_B (direct call-graph):
  ARM_B  : walks A's function body AST → only directly-called functions
  ARM_B4 : walks A's module-level imports → all functions in imported modules

Expected recall hypothesis: 7/7 = 100% (B is always in A's module or
imported by A's module in this 7-case seed set).

Expected candidate counts:
  stages.py cases          (cross_001, cross_005): ~9 candidates
  conversation_memory.py cases (cross_002–004, 006–007): ~18 candidates

For model presentation, candidates are ordered by file appearance (no re-ranking).
All candidates are shown (no top-5 truncation) since counts are small.

Comparison:
  ARM_A  : 0/7  =  0.0%  (function A source only)
  ARM_B  : 7/7  = 100.0% (oracle call-graph)
  ARM_B2 : 4/7  =  57.1% (BM25 top-5, recall@5 = 2/7)
  ARM_B3 : ???            (embedding top-5)
  ARM_B4 : ???            (module import graph, all candidates)
  ARM_B5 : see arm_b5.py  (hybrid: import graph + embedding re-rank)

Pre-committed interpretation:
  If recall = 7/7 but repair < 7/7 : structural recall is not the bottleneck;
                                      re-ranking within the set is.
  If repair = 7/7                  : small import-graph context is sufficient;
                                     hybrid (ARM_B5) is redundant.
  If recall < 7/7                  : import graph misses cross-file helpers
                                     not captured by 1-hop imports.

Usage (from openrent-agent/):
    python testfix/arm_b4.py [--attempts N] [--model MODEL] [--retrieval-only]
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
    from testfix.retriever_import_graph import retrieve_module_context
    return _extract_function_source, extract_failure, verify_fix, _patched, retrieve_module_context


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
    helpers: dict[str, tuple[str, str]],
    error_message: str,
) -> str:
    """
    Show ALL import-graph candidates. No truncation — counts are small (9-18).
    """
    block = ""
    for name, (rel_path, src) in helpers.items():
        block += f"\n--- {name} ({rel_path}) ---\n{src}\n"

    helper_section = (
        f"\nMODULE-CONTEXT FUNCTIONS (all functions in A's module and its imports — "
        f"one may contain the bug, or the bug may be in the entry-point itself):\n{block}"
        if block else ""
    )

    return (
        "You are fixing a Python bug. A test is failing. The test calls the entry-point "
        "function shown below. The bug may be inside the entry-point OR in one of the "
        "module-context helpers shown below (retrieved via the module import graph).\n\n"
        f"FAILING TEST:\n{test_source}\n\n"
        f"ENTRY-POINT FUNCTION (the function the test calls directly):\n{entry_source}\n"
        f"{helper_section}\n"
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


def run_case_b4(
    case, seed_map,
    extract_failure, verify_fix, _extract_function_source, _patched, retrieve_module_context,
    max_attempts: int, model: str,
) -> dict:
    case_id = case["case_id"]
    test_id = case["test_id"]
    target_file = case["target_file"]   # B's file
    func_name = case["target_function"] # B (broken helper)
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

    with _patched(target_path, mutated_file_source, original_file_source):
        failure_ctx = extract_failure(test_id)

    if not failure_ctx:
        return {"case_id": case_id, "error": "test passed on mutated code",
                "attempts": [], "retrieval": {}, "passed": False}

    entry_source = failure_ctx["target_source"] or mutated_func_source
    error_msg = failure_ctx["error_message"] or ""
    test_src = failure_ctx["test_source"] or ""
    entry_func_name = failure_ctx.get("target_function")
    entry_file = failure_ctx.get("target_file") or target_file  # A's file

    # Retrieve all functions from A's module + imported modules
    helpers = retrieve_module_context(
        entry_file,
        exclude_function=entry_func_name,
    )

    # Retrieval diagnostic
    correct_in_set = func_name in helpers
    # Position in ordered dict (Python 3.7+ maintains insertion order = file order)
    helper_names = list(helpers.keys())
    correct_position = (helper_names.index(func_name) + 1) if correct_in_set else None

    retrieval = {
        "candidate_count": len(helpers),
        "candidates": [
            {"position": i + 1, "function_name": name, "file_path": rel}
            for i, (name, (rel, _)) in enumerate(helpers.items())
        ],
        "correct_function": func_name,
        "correct_in_set": correct_in_set,
        "correct_position": correct_position,
        "entry_module": entry_file,
    }

    attempts: list[dict] = []
    passed_on_attempt: int | None = None

    for attempt_num in range(1, max_attempts + 1):
        prompt = _build_prompt(test_src, entry_source, helpers, error_msg)
        proposed, latency_ms = _propose_fix(prompt, model)

        if not proposed:
            attempts.append({
                "attempt": attempt_num, "error": "proposer returned empty",
                "latency_ms": round(latency_ms),
            })
            continue

        proposed_name = _parse_def_name(proposed)

        # Determine fix target
        if proposed_name and proposed_name in helpers:
            fix_file, _ = helpers[proposed_name]
            fix_func = proposed_name
        elif proposed_name and proposed_name == entry_func_name:
            fix_file = entry_file
            fix_func = proposed_name
        else:
            fix_file, fix_func = target_file, func_name

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
    parser.add_argument("--output", default="testfix/arm_b4_results.json")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--retrieval-only", action="store_true",
                        help="Show candidate sets without calling the model")
    args = parser.parse_args()

    _extract_function_source, extract_failure, verify_fix, _patched, retrieve_module_context = _import_all()

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

    print(f"ARM_B4 (module import graph): {len(cases)} cases, model={args.model}"
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

        result = run_case_b4(
            case, seed_map,
            extract_failure, verify_fix, _extract_function_source, _patched, retrieve_module_context,
            max_attempts=effective_attempts, model=args.model,
        )

        ret = result["retrieval"]
        in_set = ret.get("correct_in_set")
        cand_count = ret.get("candidate_count", 0)
        pos_str = f"@{ret.get('correct_position')}" if in_set else "MISS"

        if args.retrieval_only:
            cand_names = [c["function_name"] for c in ret.get("candidates", [])]
            print(f"in_set={in_set} pos={pos_str} count={cand_count}  set={cand_names}")
        else:
            status = f"PASS(a{result['passed_on_attempt']})" if result["passed"] else "FAIL"
            latencies = [a["latency_ms"] for a in result["attempts"] if "latency_ms" in a]
            med = sorted(latencies)[len(latencies) // 2] if latencies else 0
            print(f"{status}  in_set={in_set} pos={pos_str} count={cand_count}  (~{med}ms)")

        results.append(result)

    total = len(results)
    in_set_count = sum(1 for r in results if r["retrieval"].get("correct_in_set"))
    first_pass = sum(1 for r in results if r.get("passed_on_attempt") == 1)
    any_pass = sum(1 for r in results if r.get("passed"))
    all_latencies = [
        a["latency_ms"] for r in results
        for a in r.get("attempts", []) if "latency_ms" in a
    ]
    median_lat = sorted(all_latencies)[len(all_latencies) // 2] if all_latencies else 0
    avg_cands = sum(r["retrieval"].get("candidate_count", 0) for r in results) / total if total else 0

    by_mode = {}
    for r in results:
        mode = r.get("failure_mode", "unknown")
        by_mode.setdefault(mode, {"passed": 0, "total": 0})
        by_mode[mode]["total"] += 1
        if r.get("passed"):
            by_mode[mode]["passed"] += 1

    summary = {
        "retrieval_recall_in_set": f"{in_set_count}/{total}",
        "avg_candidate_count": round(avg_cands, 1),
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

    sep = "-" * 60
    print(f"\n{sep}")
    print(f"ARM_B4 RESULTS  model={args.model}  (module import graph)")
    print(sep)
    print(f"  ARM_A  (no helpers)        : 0/7  =  0.0%")
    print(f"  ARM_B  (oracle call-graph) : 7/7  = 100.0%")
    print(f"  ARM_B2 (BM25 top-5)        : 4/7  =  57.1%")
    if not args.retrieval_only:
        print(f"  ARM_B4 first-attempt       : {first_pass}/{total}  = {first_pass/total:.1%}")
        print(f"  ARM_B4 after-{args.attempts}-attempts    : {any_pass}/{total}  = {any_pass/total:.1%}")
        print(f"  median latency             : {median_lat} ms")
    print(f"\n  Recall in import-graph set : {in_set_count}/{total} = {in_set_count/total:.1%}")
    print(f"  Avg candidate count        : {avg_cands:.1f}")
    print(f"\n  Per-case (B=broken helper  pos=file-order position in candidate set):")
    for r in results:
        ret = r["retrieval"]
        in_set = ret.get("correct_in_set")
        pos = ret.get("correct_position")
        cnt = ret.get("candidate_count", 0)
        pos_str = f"@{pos}/{cnt}" if in_set else f"MISS/{cnt}"
        cands = [c["function_name"] for c in ret.get("candidates", [])]
        if args.retrieval_only:
            print(f"    {r['case_id']}  B={r['target_function']:<28} {pos_str:<10}  set={cands}")
        else:
            passed_str = "PASS" if r.get("passed") else "FAIL"
            print(f"    {r['case_id']}  B={r['target_function']:<28} {pos_str:<10}  {passed_str}  set={cands}")
    if not args.retrieval_only:
        print(f"\n  By failure mode:")
        for mode, counts in sorted(by_mode.items()):
            rate = counts["passed"] / counts["total"] if counts["total"] else 0
            print(f"    {mode:<45} {counts['passed']}/{counts['total']} ({rate:.0%})")
        print(f"\nFull results: {ROOT / args.output}")


if __name__ == "__main__":
    main()
