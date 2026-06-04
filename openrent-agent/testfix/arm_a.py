"""
testfix.arm_a
-------------
ARM_A baseline: Claude proposes a fix with only {test, broken function, error} as context.
No retrieval. No prior examples. Measures cold-start fix rate.

Usage (from openrent-agent/):
    python testfix/arm_a.py [--attempts N] [--output path]

Writes results to testfix/arm_a_results.json.
"""

import argparse
import contextlib
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


# ── imports ───────────────────────────────────────────────────────────────────

def _import_all():
    import sys
    sys.path.insert(0, str(ROOT))
    from testfix.extractor import _extract_function_source, extract_failure
    from testfix.verifier import verify_fix, _patched
    from testfix.seeds import SEEDS
    return _extract_function_source, extract_failure, verify_fix, _patched, SEEDS


# ── proposer (OpenAI) ─────────────────────────────────────────────────────────

def _build_prompt(test_source: str, broken_function: str, error_message: str) -> str:
    return f"""\
You are fixing a Python bug. A test is failing. Your job is to return the corrected function.

FAILING TEST:
{test_source}

CURRENT BROKEN FUNCTION:
{broken_function}

TEST ERROR:
{error_message}

Return ONLY the corrected Python function — no explanation, no markdown, no backticks.
The function must start with `def` or `async def` on the first line.
"""


def _propose_fix(prompt: str, model: str) -> tuple[str | None, float]:
    """Call OpenAI and return (proposed_source, latency_ms)."""
    import sys
    sys.path.insert(0, str(ROOT))
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
        # Strip markdown code fences if the model ignored instructions
        if content.startswith("```"):
            lines = content.splitlines()
            content = "\n".join(
                line for line in lines
                if not line.strip().startswith("```")
            ).strip()
        return content, latency_ms
    except Exception as exc:
        latency_ms = (time.perf_counter() - t0) * 1000
        return None, latency_ms


TRIAGE_LABELS = ("auto_fixable_local", "auto_fixable_cross_function", "needs_human", "insufficient_context")

_TRIAGE_PROMPT = """\
You are a software triage assistant. A Python test is failing.

FAILING TEST:
{test_source}

FUNCTION SHOWN (may or may not contain the bug — it is the function the test calls directly):
{broken_function}

TEST ERROR:
{error_message}

Classify this failure as EXACTLY ONE of these labels:
- auto_fixable_local            : the bug is inside the shown function and can be fixed from this context alone
- auto_fixable_cross_function   : the bug is in a helper or dependency NOT shown; fixing the shown function won't help
- needs_human                   : too complex or ambiguous to classify without more context
- insufficient_context          : not enough information to make any determination

Reply with ONLY the label. No explanation, no punctuation, no markdown.
"""


def _classify_failure(test_source: str, broken_function: str, error_message: str, model: str) -> tuple[str, float]:
    """Call OpenAI to classify the failure type. Returns (label, latency_ms)."""
    import sys
    sys.path.insert(0, str(ROOT))
    from openai import OpenAI
    from app.config import settings

    prompt = _TRIAGE_PROMPT.format(
        test_source=test_source,
        broken_function=broken_function,
        error_message=error_message,
    )
    client = OpenAI(api_key=settings.OPENAI_API_KEY, timeout=30.0)
    t0 = time.perf_counter()
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        latency_ms = (time.perf_counter() - t0) * 1000
        label = (response.choices[0].message.content or "").strip().lower().replace("-", "_")
        if label not in TRIAGE_LABELS:
            label = "insufficient_context"
        return label, latency_ms
    except Exception:
        latency_ms = (time.perf_counter() - t0) * 1000
        return "insufficient_context", latency_ms


# ── mutation helpers ──────────────────────────────────────────────────────────

def _apply_mutation(function_source: str, original_snippet: str, mutated_snippet: str) -> str | None:
    if original_snippet not in function_source:
        return None
    return function_source.replace(original_snippet, mutated_snippet, 1)


def _replace_in_file(file_source: str, original_func: str, new_func: str) -> str:
    if original_func not in file_source:
        return file_source
    return file_source.replace(original_func, new_func, 1)


# ── single-case runner ────────────────────────────────────────────────────────

def run_case(case, seed_map, extract_failure, verify_fix, _extract_function_source, _patched,
             max_attempts: int, model: str, triage: bool = False) -> dict:
    case_id = case["case_id"]
    test_id = case["test_id"]
    target_file = case["target_file"]
    func_name = case["target_function"]
    target_path = ROOT / target_file

    seed = seed_map.get(case_id)
    if not seed:
        return {"case_id": case_id, "error": "no seed definition", "attempts": []}

    # Read original function source
    original_func_source = _extract_function_source(target_path, func_name)
    if not original_func_source:
        return {"case_id": case_id, "error": "could not extract function", "attempts": []}

    # Build mutated function and file
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
    triage_prediction = None
    triage_latency_ms = None

    for attempt_num in range(1, max_attempts + 1):
        # Extract failure context from mutated code
        with _patched(target_path, mutated_file_source, original_file_source):
            failure_ctx = extract_failure(test_id)

        if not failure_ctx:
            attempts.append({"attempt": attempt_num, "error": "extractor returned None (test passed on mutated code?)"})
            break

        test_src = failure_ctx["test_source"] or ""
        shown_func = failure_ctx["target_source"] or mutated_func_source
        error_msg = failure_ctx["error_message"] or ""

        # Triage classification (first attempt only)
        if triage and attempt_num == 1:
            triage_prediction, triage_latency_ms = _classify_failure(
                test_src, shown_func, error_msg, model
            )

        # Propose a fix
        prompt = _build_prompt(test_src, shown_func, error_msg)
        proposed, latency_ms = _propose_fix(prompt, model)

        if not proposed:
            attempts.append({"attempt": attempt_num, "error": "proposer returned empty", "latency_ms": latency_ms})
            continue

        # Verify the proposed fix
        verify_result = verify_fix(test_id, proposed, target_file, func_name)

        attempt_record = {
            "attempt": attempt_num,
            "passed": verify_result["passed"],
            "latency_ms": round(latency_ms),
            "verify_error": verify_result.get("error"),
        }
        attempts.append(attempt_record)

        if verify_result["passed"]:
            passed_on_attempt = attempt_num
            break

    result = {
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
    if triage:
        result["triage_prediction"] = triage_prediction
        result["triage_latency_ms"] = round(triage_latency_ms) if triage_latency_ms else None
    return result


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--attempts", type=int, default=3, help="Max attempts per case")
    parser.add_argument("--model", default="gpt-4.1-mini", help="Proposer model")
    parser.add_argument("--baseline", default="testfix/baseline_cases.jsonl",
                        help="Path to baseline JSONL (relative to openrent-agent/)")
    parser.add_argument("--seeds-module", default="testfix.seeds",
                        help="Python module containing SEEDS or SEEDS_HARD list")
    parser.add_argument("--output", default="testfix/arm_a_results.json")
    parser.add_argument("--dry-run", action="store_true", help="Print cases without calling API")
    parser.add_argument("--triage", action="store_true", help="Classify each failure before fixing")
    args = parser.parse_args()

    _extract_function_source, extract_failure, verify_fix, _patched, _ = _import_all()

    # Load seeds from whichever module was specified
    import importlib
    seeds_mod = importlib.import_module(args.seeds_module)
    SEEDS = (
        getattr(seeds_mod, "SEEDS", None)
        or getattr(seeds_mod, "SEEDS_HARD", None)
        or getattr(seeds_mod, "SEEDS_CROSS", [])
    )

    # Load baseline cases
    baseline_path = ROOT / args.baseline
    cases = []
    with baseline_path.open(encoding="utf-8") as f:
        for line in f:
            c = json.loads(line.strip())
            if not c.get("exclude_from_headline") and c.get("extractor_ok") and c.get("verifier_ok"):
                cases.append(c)

    seed_map = {s["case_id"]: s for s in SEEDS}

    print(f"ARM_A: {len(cases)} cases, max {args.attempts} attempts, model={args.model}")
    if args.dry_run:
        for c in cases:
            print(f"  {c['case_id']} {c['failure_mode']} -> {c['test_id']}")
        return

    print()
    results = []
    for i, case in enumerate(cases):
        print(f"[{i+1}/{len(cases)}] {case['case_id']} ({case['failure_mode']})...", end=" ", flush=True)
        result = run_case(
            case, seed_map, extract_failure, verify_fix,
            _extract_function_source, _patched,
            max_attempts=args.attempts, model=args.model, triage=args.triage,
        )
        status = f"PASS (attempt {result['passed_on_attempt']})" if result["passed"] else "FAIL"
        latencies = [a["latency_ms"] for a in result["attempts"] if "latency_ms" in a]
        median_lat = sorted(latencies)[len(latencies) // 2] if latencies else 0
        print(f"{status}  (~{median_lat}ms)")
        results.append(result)

    # ── metrics ───────────────────────────────────────────────────────────────
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

    # ── triage accuracy (if --triage) ─────────────────────────────────────────
    triage_summary = None
    if args.triage:
        triage_correct = 0
        triage_total = 0
        triage_by_truth = {}
        for r in results:
            truth = r.get("triage_ground_truth")
            pred = r.get("triage_prediction")
            if truth and pred:
                triage_total += 1
                correct = (truth == "cross_function" and pred == "auto_fixable_cross_function") or \
                          (truth == "local" and pred == "auto_fixable_local")
                if correct:
                    triage_correct += 1
                triage_by_truth.setdefault(truth, {"correct": 0, "total": 0})
                triage_by_truth[truth]["total"] += 1
                if correct:
                    triage_by_truth[truth]["correct"] += 1
        triage_accuracy = round(triage_correct / triage_total, 3) if triage_total else None
        triage_summary = {
            "accuracy": triage_accuracy,
            "correct": triage_correct,
            "total": triage_total,
            "by_ground_truth": triage_by_truth,
        }

    summary = {
        "total_cases": total,
        "first_attempt_pass_rate": round(first_attempt_pass / total, 3) if total else 0,
        "pass_rate_after_n_attempts": round(any_pass / total, 3) if total else 0,
        "max_attempts": args.attempts,
        "median_latency_ms": median_latency,
        "smoke_test_excluded": True,
        "triage": triage_summary,
        "by_failure_mode": by_mode,
        "cases": results,
    }

    # Derive output path from baseline path if default not changed
    out_file = args.output
    if out_file == "testfix/arm_a_results.json":
        if "hard" in args.baseline:
            out_file = "testfix/arm_a_hard_results.json"
        elif "cross" in args.baseline:
            out_file = "testfix/arm_a_cross_results.json"
    out_path = ROOT / out_file
    out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"\n{'-'*50}")
    print(f"ARM_A RESULTS ({args.model}, max_attempts={args.attempts})")
    print(f"{'-'*50}")
    print(f"  first_attempt_pass_rate : {first_attempt_pass}/{total} = {summary['first_attempt_pass_rate']:.1%}")
    print(f"  pass_rate_after_{args.attempts}_attempts: {any_pass}/{total} = {summary['pass_rate_after_n_attempts']:.1%}")
    print(f"  median_latency_ms       : {median_latency}")
    print(f"  smoke_test_excluded     : True")
    if triage_summary:
        print(f"\n  Triage accuracy:")
        print(f"    {triage_summary['correct']}/{triage_summary['total']} = {triage_accuracy:.1%}")
        for truth, counts in sorted(triage_summary["by_ground_truth"].items()):
            rate = counts["correct"] / counts["total"] if counts["total"] else 0
            print(f"    truth={truth:<20} {counts['correct']}/{counts['total']} ({rate:.0%})")
    print(f"\n  By failure mode:")
    for mode, counts in sorted(by_mode.items()):
        rate = counts["passed"] / counts["total"] if counts["total"] else 0
        print(f"    {mode:<40} {counts['passed']}/{counts['total']} ({rate:.0%})")
    print(f"\nFull results: {out_path}")


if __name__ == "__main__":
    main()
