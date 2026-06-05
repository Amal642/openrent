"""
OPEN-55: mutation-conditioned test generation.

For each of the 20 cross-function seeds:
  1. Apply the mutation to get a broken codebase state.
  2. Prompt the LLM: given this mutated module source + entry-function name,
     write pytest(s) that verify the entry function's specified behaviour.
     The LLM receives NO existing test, NO mutation details, NO helper label.
  3. Validate the generated test:
       mutant  → expect FAIL  (mutation kill)
       original → expect PASS  (no false positive)
  4. Classify: killed / false_positive / both_pass / syntax_error / import_error

Precommit (§S4):
  GREEN  >= 50%  kill rate on n=20
  YELLOW 25-49%
  RED    < 25%

Usage (from openrent-agent/):
    python -m testfix.open55_testgen [--model MODEL] [--attempts N]

Default model: gpt-4.1-mini  (set --model gpt-4.1 for stronger baseline)
"""

import argparse
import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# ── seed + training-data loading ──────────────────────────────────────────────

def _load_seeds() -> list[dict]:
    from testfix.seeds_cross import SEEDS_CROSS
    return SEEDS_CROSS


# Hardcoded map — training data entry_func is unreliable for tests that call
# methods on return values (e.g. result.date() gets parsed as "date").
_ENTRY_MAP: dict[str, dict] = {
    "cross_001": {"entry_func": "detect_stage",                    "entry_file": "app/ai/stages.py"},
    "cross_002": {"entry_func": "detect_landlord_attitude",        "entry_file": "app/ai/conversation_memory.py"},
    "cross_003": {"entry_func": "latest_landlord_asked_for_phone", "entry_file": "app/ai/conversation_memory.py"},
    "cross_004": {"entry_func": "viewing_requested",               "entry_file": "app/ai/conversation_memory.py"},
    "cross_005": {"entry_func": "detect_stage",                    "entry_file": "app/ai/stages.py"},
    "cross_006": {"entry_func": "outbound_count",                  "entry_file": "app/ai/conversation_memory.py"},
    "cross_007": {"entry_func": "phone_shared_state",              "entry_file": "app/ai/personas.py"},
    "cross_008": {"entry_func": "detect_stage",                    "entry_file": "app/ai/stages.py"},
    "cross_009": {"entry_func": "detect_stage",                    "entry_file": "app/ai/stages.py"},
    "cross_010": {"entry_func": "extract_viewing_datetime",        "entry_file": "app/ai/stages.py"},
    "cross_011": {"entry_func": "extract_viewing_datetime",        "entry_file": "app/ai/stages.py"},
    "cross_012": {"entry_func": "get_conversation_style",          "entry_file": "app/ai/personas.py"},
    "cross_013": {"entry_func": "should_share_phone_now",          "entry_file": "app/ai/personas.py"},
    "cross_014": {"entry_func": "detect_landlord_attitude",        "entry_file": "app/ai/conversation_memory.py"},
    "cross_015": {"entry_func": "detect_landlord_attitude",        "entry_file": "app/ai/conversation_memory.py"},
    "cross_016": {"entry_func": "phone_shared_state",              "entry_file": "app/ai/personas.py"},
    "cross_017": {"entry_func": "outbound_count",                  "entry_file": "app/ai/conversation_memory.py"},
    "cross_018": {"entry_func": "extract_viewing_datetime",        "entry_file": "app/ai/stages.py"},
    "cross_019": {"entry_func": "detect_stage",                    "entry_file": "app/ai/stages.py"},
    "cross_020": {"entry_func": "landlord_messages",               "entry_file": "app/ai/conversation_memory.py"},
}


def _load_entry_map() -> dict[str, dict]:
    return _ENTRY_MAP


# ── pyc cache clearance ────────────────────────────────────────────────────────

def _clear_pyc(py_path: Path) -> None:
    stem = py_path.stem
    cache_dir = py_path.parent / "__pycache__"
    for pyc in cache_dir.glob(f"{stem}.*.pyc"):
        try:
            pyc.unlink()
        except OSError:
            pass


# ── mutation helpers ───────────────────────────────────────────────────────────

def _apply_seed_mutation(seed: dict) -> str | None:
    """Return the full mutated file content, or None if snippet not found."""
    target_path = ROOT / seed["target_file"]
    file_src = target_path.read_text(encoding="utf-8")

    from testfix.extractor import _extract_function_source
    func_src = _extract_function_source(target_path, seed["target_function"])
    if func_src is None or seed["original_snippet"] not in func_src:
        return None

    mutated_func = func_src.replace(seed["original_snippet"], seed["mutated_snippet"], 1)
    return file_src.replace(func_src, mutated_func, 1)


# ── prompt construction ────────────────────────────────────────────────────────

_STATUS_CONSTANTS = (ROOT / "app/db/status.py").read_text(encoding="utf-8")

def _build_prompt(entry_func: str, entry_file: str, mutated_module_src: str) -> str:
    module_dotpath = entry_file.replace("/", ".").replace("\\", ".").removesuffix(".py")
    # Last segment: e.g. "app.ai.stages" → "stages"
    module_short = module_dotpath.split(".")[-1]

    return f"""You are a test engineer. Your task is to write pytest tests that verify the correctness of `{entry_func}`.

You are given the current source of the module it lives in. The module may contain a subtle implementation bug in one of its helper functions. Your tests must be written to catch such bugs by exercising `{entry_func}` through its public interface.

=== Module source ({entry_file}) ===
{mutated_module_src}

=== Status constants (app/db/status.py) ===
{_STATUS_CONSTANTS}

=== Your task ===
Write 2–4 pytest test functions that:
1. Import `{entry_func}` as: `from {module_dotpath} import {entry_func}`
2. Call `{entry_func}` with realistic inputs and assert SPECIFIC expected return values.
3. Cover the most important behaviours and edge cases — especially cases where a subtle off-by-one, wrong key, wrong comparison operator, or wrong control-flow direction would cause a silently wrong result.
4. Do NOT directly call private helpers (names starting with `_`).
5. Each test must have at least one concrete `assert` with an expected value — no `assert result is not None` unless followed by a value check.

Return ONLY valid Python code (the import statements + the test functions). No explanation, no markdown fences.
"""


# ── LLM call ──────────────────────────────────────────────────────────────────

def _call_model(prompt: str, model: str, max_tokens: int = 1500) -> tuple[str | None, float]:
    from openai import OpenAI
    from app.config import settings

    client = OpenAI(api_key=settings.OPENAI_API_KEY, timeout=60.0)
    t0 = time.perf_counter()
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=max_tokens,
        )
        latency_ms = (time.perf_counter() - t0) * 1000
        content = (response.choices[0].message.content or "").strip()
        # Strip markdown fences
        if content.startswith("```"):
            lines = content.splitlines()
            content = "\n".join(
                line for line in lines if not line.strip().startswith("```")
            ).strip()
        return content, latency_ms
    except Exception as exc:
        return None, (time.perf_counter() - t0) * 1000


# ── generated-test validation ─────────────────────────────────────────────────

def _run_generated_test(test_code: str, label: str) -> tuple[str, str]:
    """
    Write test_code to a temp file and run pytest.
    Returns (outcome, output) where outcome is 'passed' | 'failed' | 'error'.
    """
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".py",
        prefix=f"open55_{label}_",
        dir=ROOT / "testfix",
        delete=False,
        encoding="utf-8",
    ) as f:
        f.write(test_code)
        tmp_path = Path(f.name)

    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", str(tmp_path), "--tb=short", "-q", "--no-header"],
            capture_output=True, text=True, cwd=ROOT,
        )
        output = result.stdout + result.stderr
        if result.returncode == 0:
            return "passed", output
        # Distinguish syntax/import errors from genuine test failures
        if "SyntaxError" in output or "ImportError" in output or "ModuleNotFoundError" in output:
            return "error", output
        return "failed", output
    finally:
        tmp_path.unlink(missing_ok=True)


def _classify(on_mutant: str, on_original: str) -> str:
    """
    killed         — failed on mutant, passed on original  (desired)
    inverted       — passed on mutant, failed on original  (model conformed to mutation)
    false_positive — failed on both  (test expects wrong values throughout)
    both_pass      — passed on both  (test too weak to detect mutation)
    syntax_error   — error on either side
    """
    if on_mutant == "error" or on_original == "error":
        return "syntax_error"
    if on_mutant == "failed" and on_original == "passed":
        return "killed"
    if on_mutant == "passed" and on_original == "failed":
        return "inverted"
    if on_mutant == "failed" and on_original == "failed":
        return "false_positive"
    return "both_pass"


# ── secondary metric helpers ───────────────────────────────────────────────────

def _calls_private_helper(test_code: str) -> bool:
    """True if generated test directly calls a private function (._something()"""
    return bool(re.search(r'\b_[a-z]\w*\(', test_code))


def _has_real_assertion(test_code: str) -> bool:
    """True if test has at least one assert with a concrete expected value."""
    for m in re.finditer(r'assert\s+(.+)', test_code):
        clause = m.group(1).strip()
        if ' == ' in clause or ' is True' in clause or ' is False' in clause:
            return True
    return False


def _count_test_functions(test_code: str) -> int:
    return len(re.findall(r'^def test_', test_code, re.MULTILINE))


# ── main loop ─────────────────────────────────────────────────────────────────

def run(model: str, attempts: int) -> list[dict]:
    seeds = _load_seeds()
    entry_map = _load_entry_map()
    results = []

    for seed in seeds:
        case_id = seed["case_id"]
        entry_info = entry_map.get(case_id)
        if not entry_info:
            print(f"[{case_id}] SKIP — no entry_func in training data")
            continue

        entry_func = entry_info["entry_func"]
        entry_file = entry_info["entry_file"]
        target_path = ROOT / seed["target_file"]

        mutated_src = _apply_seed_mutation(seed)
        if mutated_src is None:
            print(f"[{case_id}] SKIP — mutation snippet not found")
            continue

        prompt = _build_prompt(entry_func, entry_file, mutated_src)

        best_outcome = "both_pass"
        best_code = None
        best_on_original = "passed"
        latency_total = 0.0

        for attempt in range(1, attempts + 1):
            generated, latency_ms = _call_model(prompt, model)
            latency_total += latency_ms

            if not generated:
                print(f"  [{case_id}] attempt {attempt} — LLM returned nothing")
                continue

            # Validate on mutant
            original_src = target_path.read_text(encoding="utf-8")
            target_path.write_text(mutated_src, encoding="utf-8")
            _clear_pyc(target_path)
            try:
                on_mutant, out_mutant = _run_generated_test(generated, f"{case_id}_mutant")
            finally:
                target_path.write_text(original_src, encoding="utf-8")
                _clear_pyc(target_path)

            # Validate on original
            on_original, out_original = _run_generated_test(generated, f"{case_id}_orig")

            outcome = _classify(on_mutant, on_original)
            print(
                f"  [{case_id}] attempt {attempt}  on_mutant={on_mutant}  "
                f"on_original={on_original}  outcome={outcome}  ({latency_ms:.0f}ms)"
            )

            if outcome == "killed":
                best_outcome = "killed"
                best_code = generated
                best_on_original = on_original
                break
            if best_outcome == "both_pass" and outcome != "syntax_error":
                best_outcome = outcome
                best_code = generated
                best_on_original = on_original

        result = {
            "case_id": case_id,
            "entry_func": entry_func,
            "target_function": seed["target_function"],
            "outcome": best_outcome,
            "calls_private_helper": _calls_private_helper(best_code or ""),
            "has_real_assertion": _has_real_assertion(best_code or ""),
            "n_test_functions": _count_test_functions(best_code or ""),
            "latency_ms": round(latency_total),
            "generated_code": best_code,
        }
        results.append(result)

    return results


def _print_summary(results: list[dict]) -> None:
    from collections import Counter
    n = len(results)
    outcomes = Counter(r["outcome"] for r in results)
    killed = outcomes["killed"]
    kill_rate = killed / n if n else 0.0

    print()
    print("=" * 68)
    print(f"OPEN-55 TEST GENERATION  n={n}  model runs")
    print("=" * 68)
    print(f"  killed (mutation kill)   : {killed}/{n} = {kill_rate:.1%}")
    print(f"  both_pass (too weak)     : {outcomes['both_pass']}/{n}")
    print(f"  inverted (conformed)     : {outcomes['inverted']}/{n}  <- model read mutation, wrote conforming test")
    print(f"  false_positive (bad test): {outcomes['false_positive']}/{n}")
    print(f"  syntax_error             : {outcomes['syntax_error']}/{n}")
    print()
    print("Secondary metrics:")
    calls_private = sum(1 for r in results if r["calls_private_helper"])
    no_real_assert = sum(1 for r in results if not r["has_real_assertion"])
    print(f"  tests calling private helpers : {calls_private}/{n}")
    print(f"  tests with no concrete assert : {no_real_assert}/{n}")
    print(f"  avg test functions generated  : {sum(r['n_test_functions'] for r in results)/n:.1f}")
    print()

    print("§S4 precommit:")
    if kill_rate >= 0.50:
        verdict = "GREEN"
    elif kill_rate >= 0.25:
        verdict = "YELLOW"
    else:
        verdict = "RED"
    print(f"  {verdict}  kill_rate={kill_rate:.1%}  (GREEN>=50%, YELLOW>=25%, RED<25%)")
    print()

    print("Per-case:")
    print(f"  {'case_id':<12} {'entry_func':<28} {'B':<30} {'outcome'}")
    print("  " + "-" * 80)
    for r in results:
        print(
            f"  {r['case_id']:<12} {r['entry_func']:<28} {r['target_function']:<30} {r['outcome']}"
        )


# ── CLI ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="OPEN-55 mutation-conditioned test generation")
    parser.add_argument("--model", default="gpt-4.1-mini", help="OpenAI model to use")
    parser.add_argument("--attempts", type=int, default=1, help="Attempts per seed")
    parser.add_argument("--out", default="testfix/open55_results.json", help="Output JSON path")
    args = parser.parse_args()

    print(f"OPEN-55 test generation  model={args.model}  attempts={args.attempts}  n=20 seeds")
    print()

    results = run(model=args.model, attempts=args.attempts)
    _print_summary(results)

    out_path = ROOT / args.out
    out_path.write_text(
        json.dumps({"model": args.model, "attempts": args.attempts, "results": results}, indent=2),
        encoding="utf-8",
    )
    print(f"\nResults: {out_path}")
