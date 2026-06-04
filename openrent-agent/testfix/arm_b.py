"""
testfix.arm_b
-------------
ARM_B retrieval arm: Claude proposes a fix with {test, entry-point function A,
all helper functions called by A (retrieved from app/ while B is mutated), error}.

The model can now see broken helper B alongside the correct entry-point A.

ARM_A cross-function baseline: 0/7 = 0%.
ARM_B target: significantly above 0% — proves retrieval adds value.

Usage (from openrent-agent/):
    python testfix/arm_b.py [--attempts N] [--model MODEL] [--output path]
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
    from testfix.retriever import retrieve_helpers
    return _extract_function_source, extract_failure, verify_fix, _patched, retrieve_helpers


def _parse_def_name(source: str) -> str | None:
    """Return the function name from the first def/async def in source."""
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
    helper_block = ""
    for name, (rel_path, src) in helpers.items():
        helper_block += f"\n--- {name} ({rel_path}) ---\n{src}\n"

    helper_section = (
        f"\nHELPER FUNCTIONS CALLED BY THE ABOVE:\n{helper_block}"
        if helper_block else ""
    )

    return (
        "You are fixing a Python bug. A test is failing. The test calls the entry-point "
        "function shown below, but the bug may be inside one of its helper functions.\n\n"
        "Your job: identify the broken function (entry point OR a helper) and return its "
        "corrected source.\n\n"
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


def run_case_b(
    case, seed_map,
    extract_failure, verify_fix, _extract_function_source, _patched, retrieve_helpers,
    max_attempts: int, model: str,
) -> dict:
    case_id = case["case_id"]
    test_id = case["test_id"]
    target_file = case["target_file"]   # B's file
    func_name = case["target_function"] # B (the helper with the bug)
    target_path = ROOT / target_file

    seed = seed_map.get(case_id)
    if not seed:
        return {"case_id": case_id, "error": "no seed definition", "attempts": []}

    original_func_source = _extract_function_source(target_path, func_name)
    if not original_func_source:
        return {"case_id": case_id, "error": "could not extract function", "attempts": []}

    mutated_func_source = _apply_mutation(
        original_func_source, seed["original_snippet"], seed["mutated_snippet"]
    )
    if mutated_func_source is None:
        return {"case_id": case_id, "error": "snippet not found in function", "attempts": []}

    original_file_source = target_path.read_text(encoding="utf-8")
    mutated_file_source = _replace_in_file(
        original_file_source, original_func_source, mutated_func_source
    )

    attempts = []
    passed_on_attempt = None
    last_failure_ctx = None

    for attempt_num in range(1, max_attempts + 1):
        # Patch B's file, extract failure context and retrieve helpers while file is mutated
        with _patched(target_path, mutated_file_source, original_file_source):
            failure_ctx = extract_failure(test_id)
            if not failure_ctx:
                attempts.append({
                    "attempt": attempt_num,
                    "error": "extractor returned None (test passed on mutated code?)",
                })
                break

            last_failure_ctx = failure_ctx
            entry_source = failure_ctx["target_source"] or mutated_func_source
            error_msg = failure_ctx["error_message"] or ""
            test_src = failure_ctx["test_source"] or ""

            # Retrieve helpers while B is still mutated on disk
            helpers = retrieve_helpers(entry_source)

        # File is now restored — propose fix from collected context
        prompt = _build_prompt(test_src, entry_source, helpers, error_msg)
        proposed, latency_ms = _propose_fix(prompt, model)

        if not proposed:
            attempts.append({
                "attempt": attempt_num,
                "error": "proposer returned empty",
                "latency_ms": round(latency_ms),
                "helpers_retrieved": list(helpers.keys()),
            })
            continue

        # Determine which function+file to verify against
        proposed_name = _parse_def_name(proposed)
        if proposed_name and proposed_name in helpers:
            # Model returned a recognized helper — use its file
            fix_file, _ = helpers[proposed_name]
            fix_func = proposed_name
        elif proposed_name and last_failure_ctx and proposed_name == last_failure_ctx.get("target_function"):
            # Model returned the entry-point function
            fix_file = last_failure_ctx.get("target_file") or target_file
            fix_func = proposed_name
        else:
            # Unknown or unparseable — fall back to baseline target (B)
            fix_file = target_file
            fix_func = func_name

        verify_result = verify_fix(test_id, proposed, fix_file, fix_func)

        attempt_record = {
            "attempt": attempt_num,
            "passed": verify_result["passed"],
            "proposed_function": proposed_name,
            "fix_function": fix_func,
            "fix_file": fix_file,
            "helpers_retrieved": list(helpers.keys()),
            "latency_ms": round(latency_ms),
            "verify_error": verify_result.get("error"),
        }
        attempts.append(attempt_record)

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
        "attempts": attempts,
        "error": None,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--attempts", type=int, default=3, help="Max attempts per case")
    parser.add_argument("--model", default="gpt-4.1-mini", help="Proposer model")
    parser.add_argument("--baseline", default="testfix/baseline_cross_function.jsonl",
                        help="Path to baseline JSONL (relative to openrent-agent/)")
    parser.add_argument("--seeds-module", default="testfix.seeds_cross",
                        help="Python module containing SEEDS_CROSS list")
    parser.add_argument("--output", default="testfix/arm_b_results.json")
    parser.add_argument("--dry-run", action="store_true", help="Print cases without calling API")
    args = parser.parse_args()

    _extract_function_source, extract_failure, verify_fix, _patched, retrieve_helpers = _import_all()

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

    print(f"ARM_B: {len(cases)} cases, max {args.attempts} attempts, model={args.model}")
    if args.dry_run:
        for c in cases:
            print(f"  {c['case_id']} {c['failure_mode']} -> {c['test_id']}")
        return

    print()
    results = []
    for i, case in enumerate(cases):
        print(f"[{i+1}/{len(cases)}] {case['case_id']} ({case['failure_mode']})...", end=" ", flush=True)
        result = run_case_b(
            case, seed_map,
            extract_failure, verify_fix, _extract_function_source, _patched, retrieve_helpers,
            max_attempts=args.attempts, model=args.model,
        )
        status = f"PASS (attempt {result['passed_on_attempt']})" if result["passed"] else "FAIL"
        latencies = [a["latency_ms"] for a in result["attempts"] if "latency_ms" in a]
        median_lat = sorted(latencies)[len(latencies) // 2] if latencies else 0
        helpers_example = result["attempts"][0].get("helpers_retrieved", []) if result["attempts"] else []
        print(f"{status}  (~{median_lat}ms)  helpers={helpers_example}")
        results.append(result)

    total = len(results)
    first_attempt_pass = sum(1 for r in results if r.get("passed_on_attempt") == 1)
    any_pass = sum(1 for r in results if r.get("passed"))
    all_latencies = [
        a["latency_ms"]
        for r in results for a in r.get("attempts", [])
        if "latency_ms" in a
    ]
    median_latency = sorted(all_latencies)[len(all_latencies) // 2] if all_latencies else 0

    by_mode = {}
    for r in results:
        mode = r.get("failure_mode", "unknown")
        by_mode.setdefault(mode, {"passed": 0, "total": 0})
        by_mode[mode]["total"] += 1
        if r.get("passed"):
            by_mode[mode]["passed"] += 1

    summary = {
        "total_cases": total,
        "first_attempt_pass_rate": round(first_attempt_pass / total, 3) if total else 0,
        "pass_rate_after_n_attempts": round(any_pass / total, 3) if total else 0,
        "max_attempts": args.attempts,
        "median_latency_ms": median_latency,
        "arm_a_baseline": "0/7 = 0.0%",
        "by_failure_mode": by_mode,
        "cases": results,
    }

    out_path = ROOT / args.output
    out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"\n{'-'*50}")
    print(f"ARM_B RESULTS ({args.model}, max_attempts={args.attempts})")
    print(f"{'-'*50}")
    print(f"  ARM_A baseline            : 0/7 = 0.0%")
    print(f"  first_attempt_pass_rate   : {first_attempt_pass}/{total} = {summary['first_attempt_pass_rate']:.1%}")
    print(f"  pass_rate_after_{args.attempts}_attempts : {any_pass}/{total} = {summary['pass_rate_after_n_attempts']:.1%}")
    print(f"  median_latency_ms         : {median_latency}")
    print(f"\n  By failure mode:")
    for mode, counts in sorted(by_mode.items()):
        rate = counts["passed"] / counts["total"] if counts["total"] else 0
        print(f"    {mode:<45} {counts['passed']}/{counts['total']} ({rate:.0%})")
    print(f"\nFull results: {out_path}")


if __name__ == "__main__":
    main()
