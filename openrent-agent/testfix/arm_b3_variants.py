"""
testfix.arm_b3_variants
-----------------------
Presentation/selection variants of ARM_B3 (embedding top-K retrieval).

Tests whether repair rate is driven by:
  (a) retrieval breadth   — top-3 vs top-5 vs top-8
  (b) candidate framing   — bare source vs source with one-line docstring
  (c) explicit localisation — one-prompt-fix vs two-stage (select → repair)

Hypothesis: a two-stage localiser→repairer (B3e) will outperform any single-
prompt variant on cases where B is in the candidate set but the model fails to
identify it correctly when shown alongside distractors.

Variants
--------
  B3a : top-3  embedding, single-prompt fix
  B3b : top-5  embedding, single-prompt fix  (ARM_B3 baseline rerun)
  B3c : top-8  embedding, single-prompt fix
  B3d : top-5  embedding, single-prompt fix + one-line rationale per candidate
  B3e : top-5  embedding, two-stage (stage-1 selects function → stage-2 fixes it)

All variants share one embedding corpus build at startup.
Same model, same verifier, same _patched-during-verification rule as ARM_B3.

Usage (from openrent-agent/):
    python testfix/arm_b3_variants.py [--attempts N] [--model MODEL]
    python testfix/arm_b3_variants.py --variants B3a,B3e   # subset
    python testfix/arm_b3_variants.py --retrieval-only      # skip model calls
"""

import argparse
import ast
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

VARIANT_CONFIGS = [
    {"name": "B3a", "top_k": 3, "mode": "standard"},
    {"name": "B3b", "top_k": 5, "mode": "standard"},   # ARM_B3 baseline
    {"name": "B3c", "top_k": 8, "mode": "standard"},
    {"name": "B3d", "top_k": 5, "mode": "rationale"},
    {"name": "B3e", "top_k": 5, "mode": "two_stage"},
]


def _import_all():
    sys.path.insert(0, str(ROOT))
    from testfix.extractor import _extract_function_source, extract_failure
    from testfix.verifier import verify_fix, _patched
    from testfix.retriever_embedding import build_corpus, build_query
    return _extract_function_source, extract_failure, verify_fix, _patched, build_corpus, build_query


# ── helpers ────────────────────────────────────────────────────────────────────

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


def _parse_selected_name(reply: str, valid_names: set[str]) -> str | None:
    """
    Extract a function name from a stage-1 selection reply.
    Accepts: bare function name, or name embedded in a short sentence.
    Returns None if nothing in valid_names can be found.
    """
    reply = reply.strip()
    # Exact match first
    if reply in valid_names:
        return reply
    # Find any valid name appearing in the reply
    for name in valid_names:
        if re.search(r"\b" + re.escape(name) + r"\b", reply):
            return name
    return None


def _docstring_first_line(source: str) -> str:
    """
    Return the first line of the function's docstring, or empty string.
    Used for B3d rationale mode.
    """
    try:
        tree = ast.parse(source)
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if (node.body
                        and isinstance(node.body[0], ast.Expr)
                        and isinstance(node.body[0].value, ast.Constant)
                        and isinstance(node.body[0].value.value, str)):
                    doc = node.body[0].value.value.strip()
                    return doc.splitlines()[0][:100]
    except SyntaxError:
        pass
    return ""


# ── prompt builders ────────────────────────────────────────────────────────────

def _build_standard_prompt(test_source, entry_source, candidates, error_message, top_k):
    label = f"TOP-{top_k} CANDIDATE HELPER FUNCTIONS (embedding similarity)"
    block = ""
    for c in candidates:
        block += f"\n--- Candidate {c['rank']}: {c['function_name']} ({c['file_path']}) ---\n{c['source']}\n"
    cand_section = (
        f"\n{label} — one may contain the bug, or the bug may be in the entry-point:\n{block}"
        if block else ""
    )
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


def _build_rationale_prompt(test_source, entry_source, candidates, error_message):
    """B3d: each candidate gets a one-line docstring description before its source."""
    block = ""
    for c in candidates:
        desc = _docstring_first_line(c["source"])
        desc_line = f"  [{desc}]\n" if desc else ""
        block += (
            f"\n--- Candidate {c['rank']}: {c['function_name']} ({c['file_path']}) ---\n"
            f"{desc_line}{c['source']}\n"
        )
    cand_section = (
        "\nTOP-5 CANDIDATE HELPER FUNCTIONS (embedding similarity; description from docstring):\n"
        + block
        if block else ""
    )
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


def _build_localise_prompt(test_source, entry_source, candidates, error_message):
    """B3e stage-1: show full candidate sources, ask for just the function name to fix."""
    block = ""
    for c in candidates:
        block += f"\n--- Candidate {c['rank']}: {c['function_name']} ({c['file_path']}) ---\n{c['source']}\n"

    return (
        "You are debugging a Python test failure. The test calls the entry-point function "
        "below, but the bug may be in one of its helper functions.\n\n"
        f"FAILING TEST:\n{test_source}\n\n"
        f"ENTRY-POINT FUNCTION:\n{entry_source}\n"
        f"\nCANDIDATE HELPER FUNCTIONS:\n{block}\n"
        f"TEST ERROR:\n{error_message}\n\n"
        "Which single function most likely contains the bug — the entry-point or one of "
        "the candidates?\n\n"
        "Reply with ONLY the function name. Nothing else."
    )


def _build_repair_prompt(test_source, entry_source, selected_name, selected_source, error_message):
    """B3e stage-2: fix the single selected function."""
    if selected_source:
        target_section = f"\nFUNCTION TO FIX ({selected_name}):\n{selected_source}\n"
    else:
        target_section = f"\nFUNCTION TO FIX: {selected_name} (source not available — fix the entry-point)\n"

    return (
        "You are fixing a Python bug. A test is failing.\n\n"
        f"FAILING TEST:\n{test_source}\n\n"
        f"ENTRY-POINT FUNCTION (the function the test calls directly):\n{entry_source}\n"
        f"{target_section}\n"
        f"TEST ERROR:\n{error_message}\n\n"
        "Return ONLY the corrected function — no explanation, no markdown, no backticks.\n"
        "The function must start with `def` or `async def` on the first line."
    )


# ── model call ─────────────────────────────────────────────────────────────────

def _call_model(prompt: str, model: str, max_tokens: int = 1024) -> tuple[str | None, float]:
    from openai import OpenAI
    from app.config import settings

    client = OpenAI(api_key=settings.OPENAI_API_KEY, timeout=30.0)
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
        # Strip markdown fences if model wraps code
        if content.startswith("```"):
            lines = content.splitlines()
            content = "\n".join(
                line for line in lines if not line.strip().startswith("```")
            ).strip()
        return content, latency_ms
    except Exception:
        return None, (time.perf_counter() - t0) * 1000


# ── mutation helpers ───────────────────────────────────────────────────────────

def _apply_mutation(func_src, orig_snip, mut_snip):
    if orig_snip not in func_src:
        return None
    return func_src.replace(orig_snip, mut_snip, 1)


def _replace_in_file(file_src, orig_func, new_func):
    if orig_func not in file_src:
        return file_src
    return file_src.replace(orig_func, new_func, 1)


# ── per-case runner ────────────────────────────────────────────────────────────

def run_case(
    case, seed_map,
    extract_failure, verify_fix, _extract_function_source, _patched,
    emb_index, build_query,
    variant_config: dict,
    max_attempts: int,
    model: str,
) -> dict:
    case_id = case["case_id"]
    test_id = case["test_id"]
    target_file = case["target_file"]
    func_name = case["target_function"]
    target_path = ROOT / target_file
    mode = variant_config["mode"]
    top_k = variant_config["top_k"]

    seed = seed_map.get(case_id)
    if not seed:
        return {"case_id": case_id, "error": "no seed", "passed": False,
                "attempts": [], "retrieval": {}}

    original_func_source = _extract_function_source(target_path, func_name)
    if not original_func_source:
        return {"case_id": case_id, "error": "extract failed", "passed": False,
                "attempts": [], "retrieval": {}}

    mutated_func_source = _apply_mutation(
        original_func_source, seed["original_snippet"], seed["mutated_snippet"]
    )
    if mutated_func_source is None:
        return {"case_id": case_id, "error": "snippet not found", "passed": False,
                "attempts": [], "retrieval": {}}

    original_file_source = target_path.read_text(encoding="utf-8")
    mutated_file_source = _replace_in_file(
        original_file_source, original_func_source, mutated_func_source
    )

    with _patched(target_path, mutated_file_source, original_file_source):
        failure_ctx = extract_failure(test_id)

    if not failure_ctx:
        return {"case_id": case_id, "error": "test passed on mutant", "passed": False,
                "attempts": [], "retrieval": {}}

    entry_source = failure_ctx["target_source"] or mutated_func_source
    error_msg = failure_ctx["error_message"] or ""
    test_src = failure_ctx["test_source"] or ""
    pytest_out = failure_ctx.get("pytest_output", "")
    entry_func_name = failure_ctx.get("target_function")

    test_name = test_id.rsplit("::", 1)[-1] if "::" in test_id else ""
    query_text = build_query(test_src, error_msg, test_name, pytest_out)
    candidates = emb_index.query(query_text, top_k=top_k, exclude_function=entry_func_name)

    # Retrieval diagnostic
    correct_rank: int | None = None
    for c in candidates:
        if c["function_name"] == func_name:
            correct_rank = c["rank"]
            break

    retrieval = {
        "top_k": top_k,
        "candidates": [
            {"rank": c["rank"], "score": c["score"],
             "function_name": c["function_name"], "file_path": c["file_path"]}
            for c in candidates
        ],
        "correct_function": func_name,
        "correct_rank": correct_rank,
        "correct_in_top_k": correct_rank is not None,
    }

    if max_attempts == 0:
        return {"case_id": case_id, "passed": False, "passed_on_attempt": None,
                "retrieval": retrieval, "attempts": [], "error": None}

    cand_map = {c["function_name"]: c["file_path"] for c in candidates}
    cand_source_map = {c["function_name"]: c["source"] for c in candidates}

    attempts: list[dict] = []
    passed_on_attempt: int | None = None

    for attempt_num in range(1, max_attempts + 1):

        if mode == "standard":
            prompt = _build_standard_prompt(test_src, entry_source, candidates, error_msg, top_k)
            proposed, latency_ms = _call_model(prompt, model)
            if not proposed:
                attempts.append({"attempt": attempt_num, "error": "empty", "latency_ms": 0})
                continue
            proposed_name = _parse_def_name(proposed)
            stage1_selected = None

        elif mode == "rationale":
            prompt = _build_rationale_prompt(test_src, entry_source, candidates, error_msg)
            proposed, latency_ms = _call_model(prompt, model)
            if not proposed:
                attempts.append({"attempt": attempt_num, "error": "empty", "latency_ms": 0})
                continue
            proposed_name = _parse_def_name(proposed)
            stage1_selected = None

        elif mode == "two_stage":
            # Stage 1: localise
            s1_prompt = _build_localise_prompt(test_src, entry_source, candidates, error_msg)
            s1_reply, s1_latency = _call_model(s1_prompt, model, max_tokens=32)

            valid_names = set(cand_map.keys()) | ({entry_func_name} if entry_func_name else set())
            stage1_selected = _parse_selected_name(s1_reply or "", valid_names)

            # Resolve selected function source
            if stage1_selected and stage1_selected in cand_source_map:
                sel_source = cand_source_map[stage1_selected]
                sel_file = cand_map[stage1_selected]
            elif stage1_selected == entry_func_name:
                sel_source = entry_source
                sel_file = failure_ctx.get("target_file") or target_file
            else:
                # Fallback: fix entry-point
                stage1_selected = entry_func_name
                sel_source = entry_source
                sel_file = failure_ctx.get("target_file") or target_file

            # Stage 2: repair
            s2_prompt = _build_repair_prompt(
                test_src, entry_source, stage1_selected, sel_source, error_msg
            )
            s2_reply, s2_latency = _call_model(s2_prompt, model)
            latency_ms = s1_latency + s2_latency
            proposed = s2_reply
            if not proposed:
                attempts.append({
                    "attempt": attempt_num, "error": "stage2 empty",
                    "stage1_selected": stage1_selected, "latency_ms": round(latency_ms),
                })
                continue
            proposed_name = _parse_def_name(proposed)

        else:
            raise ValueError(f"Unknown mode: {mode}")

        # Resolve fix target
        if proposed_name and proposed_name in cand_map:
            fix_file, fix_func = cand_map[proposed_name], proposed_name
        elif proposed_name and proposed_name == entry_func_name:
            fix_file = failure_ctx.get("target_file") or target_file
            fix_func = proposed_name
        else:
            fix_file, fix_func = target_file, func_name

        with _patched(target_path, mutated_file_source, original_file_source):
            verify_result = verify_fix(test_id, proposed, fix_file, fix_func)

        rec = {
            "attempt": attempt_num,
            "passed": verify_result["passed"],
            "proposed_function": proposed_name,
            "fix_function": fix_func,
            "fix_file": fix_file,
            "latency_ms": round(latency_ms),
            "verify_error": verify_result.get("error"),
        }
        if mode == "two_stage":
            rec["stage1_selected"] = stage1_selected
            rec["stage1_correct"] = (stage1_selected == func_name)
        attempts.append(rec)

        if verify_result["passed"]:
            passed_on_attempt = attempt_num
            break

    return {
        "case_id": case_id,
        "failure_mode": case.get("failure_mode"),
        "target_function": func_name,
        "target_file": target_file,
        "passed": passed_on_attempt is not None,
        "passed_on_attempt": passed_on_attempt,
        "retrieval": retrieval,
        "attempts": attempts,
        "error": None,
    }


# ── variant runner ─────────────────────────────────────────────────────────────

def run_variant(
    variant_config, cases, seed_map,
    extract_failure, verify_fix, _extract_function_source, _patched,
    emb_index, build_query,
    max_attempts: int, model: str, retrieval_only: bool,
) -> dict:
    name = variant_config["name"]
    top_k = variant_config["top_k"]
    mode = variant_config["mode"]
    effective_attempts = 0 if retrieval_only else max_attempts

    print(f"\n--- {name} (top_k={top_k}, mode={mode}) ---")
    results = []
    for i, case in enumerate(cases):
        fn = case["target_function"]
        print(f"  [{i+1}/{len(cases)}] {case['case_id']} (B={fn})...", end=" ", flush=True)
        result = run_case(
            case, seed_map,
            extract_failure, verify_fix, _extract_function_source, _patched,
            emb_index, build_query,
            variant_config, effective_attempts, model,
        )
        ret = result["retrieval"]
        rank_str = f"B@{ret.get('correct_rank', 'MISS')}"
        cand_names = [c["function_name"] for c in ret.get("candidates", [])]

        if retrieval_only:
            print(f"{rank_str}  top{top_k}={cand_names}")
        else:
            status = f"PASS(a{result['passed_on_attempt']})" if result["passed"] else "FAIL"
            lats = [a["latency_ms"] for a in result["attempts"] if "latency_ms" in a]
            med = sorted(lats)[len(lats) // 2] if lats else 0
            # For two-stage, show stage1 selection
            if mode == "two_stage" and result["attempts"]:
                s1 = result["attempts"][0].get("stage1_selected", "?")
                s1c = result["attempts"][0].get("stage1_correct", False)
                print(f"{status}  {rank_str}  sel={s1}({'ok' if s1c else 'wrong'})  (~{med}ms)")
            else:
                print(f"{status}  {rank_str}  (~{med}ms)")

        results.append(result)

    total = len(results)
    in_topk = sum(1 for r in results if r["retrieval"].get("correct_in_top_k"))
    first_pass = sum(1 for r in results if r.get("passed_on_attempt") == 1)
    any_pass = sum(1 for r in results if r.get("passed"))
    all_lats = [a["latency_ms"] for r in results for a in r.get("attempts", []) if "latency_ms" in a]
    median_lat = sorted(all_lats)[len(all_lats) // 2] if all_lats else 0

    # Two-stage selection accuracy
    stage1_correct = None
    if mode == "two_stage":
        s1_hits = sum(
            1 for r in results
            for a in r.get("attempts", [])
            if a.get("stage1_correct")
        )
        s1_total = sum(1 for r in results if r.get("attempts"))
        stage1_correct = f"{s1_hits}/{s1_total}"

    return {
        "variant": name,
        "top_k": top_k,
        "mode": mode,
        "recall_at_k": f"{in_topk}/{total}",
        "first_attempt_pass": f"{first_pass}/{total}",
        "any_pass": f"{any_pass}/{total}",
        "pass_rate": round(any_pass / total, 3) if total else 0,
        "median_latency_ms": median_lat,
        "stage1_accuracy": stage1_correct,
        "cases": results,
    }


# ── main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--model", default="gpt-4.1-mini")
    parser.add_argument("--baseline", default="testfix/baseline_cross_function.jsonl")
    parser.add_argument("--seeds-module", default="testfix.seeds_cross")
    parser.add_argument("--output", default="testfix/arm_b3_variants_results.json")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--retrieval-only", action="store_true")
    parser.add_argument("--variants", default="",
                        help="Comma-separated subset, e.g. B3a,B3e (default: all)")
    args = parser.parse_args()

    _extract_function_source, extract_failure, verify_fix, _patched, build_corpus, build_query = _import_all()

    print("Building embedding corpus from app/...", flush=True)
    emb_index = build_corpus()
    print(f"  {emb_index.size} functions embedded.")

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

    selected_names = {v.strip() for v in args.variants.split(",") if v.strip()}
    configs = [v for v in VARIANT_CONFIGS
               if not selected_names or v["name"] in selected_names]

    if args.dry_run:
        print(f"\nWould run {len(configs)} variants on {len(cases)} cases:")
        for v in configs:
            print(f"  {v['name']}  top_k={v['top_k']}  mode={v['mode']}")
        return

    print(f"\nRunning {len(configs)} variants × {len(cases)} cases, "
          f"model={args.model}, attempts={args.attempts}"
          + (" [retrieval-only]" if args.retrieval_only else ""))

    all_variant_results = []
    for vc in configs:
        vr = run_variant(
            vc, cases, seed_map,
            extract_failure, verify_fix, _extract_function_source, _patched,
            emb_index, build_query,
            max_attempts=args.attempts, model=args.model,
            retrieval_only=args.retrieval_only,
        )
        all_variant_results.append(vr)

    # ── comparison table ───────────────────────────────────────────────────────
    sep = "=" * 74
    print(f"\n{sep}")
    print(f"ARM_B3 VARIANTS — COMPARISON  model={args.model}  corpus={emb_index.size} fns")
    print(sep)
    print(f"{'Variant':<8} {'top_k':<6} {'mode':<12} {'recall@K':<10} {'1st-pass':<10} "
          f"{'any-pass':<10} {'pass%':<8} {'med_ms':<8} {'sel_acc'}")
    print("-" * 74)
    for vr in all_variant_results:
        sel = vr["stage1_accuracy"] or "—"
        print(f"{vr['variant']:<8} {vr['top_k']:<6} {vr['mode']:<12} "
              f"{vr['recall_at_k']:<10} {vr['first_attempt_pass']:<10} "
              f"{vr['any_pass']:<10} {vr['pass_rate']:<8.1%} "
              f"{vr['median_latency_ms']:<8} {sel}")
    print(sep)
    print(f"  ARM_B3 baseline (§OPEN-51)  : 5/7 = 71.4%  (top-5, single-prompt)")
    print(f"  ARM_B  oracle call-graph     : 7/7 = 100.0%")
    print(f"  ARM_A  no retrieval          : 0/7 =   0.0%")

    # ── per-case matrix ────────────────────────────────────────────────────────
    print(f"\nPer-case pass matrix:")
    header = f"{'case_id':<14}"
    for vr in all_variant_results:
        header += f" {vr['variant']:<8}"
    print(header)
    print("-" * (14 + 9 * len(all_variant_results)))
    for i, case in enumerate(cases):
        cid = case["case_id"]
        row = f"{cid:<14}"
        for vr in all_variant_results:
            r = vr["cases"][i]
            if r.get("passed"):
                row += f" {'PASS':<8}"
            elif r.get("error"):
                row += f" {'ERR':<8}"
            else:
                row += f" {'FAIL':<8}"
        fn = case["target_function"]
        print(row + f"  B={fn}")

    # Two-stage selection breakdown
    two_stage_results = [vr for vr in all_variant_results if vr["mode"] == "two_stage"]
    if two_stage_results and not args.retrieval_only:
        print(f"\nTwo-stage (B3e) selection accuracy per case:")
        for vr in two_stage_results:
            for r in vr["cases"]:
                if not r["attempts"]:
                    continue
                a = r["attempts"][0]
                sel = a.get("stage1_selected", "?")
                ok = a.get("stage1_correct", False)
                fn = r["target_function"]
                status = "PASS" if r.get("passed") else "FAIL"
                print(f"  {r['case_id']:<14} B={fn:<28} sel={sel:<28} "
                      f"sel_ok={ok}  end={status}")

    if not args.retrieval_only:
        out_path = ROOT / args.output
        # Strip full case source from output to keep file manageable
        summary = {
            "model": args.model,
            "corpus_size": emb_index.size,
            "max_attempts": args.attempts,
            "arm_b3_baseline": "5/7 = 71.4%",
            "arm_b_oracle": "7/7 = 100.0%",
            "variants": [
                {k: v for k, v in vr.items() if k != "cases"}
                | {"cases": [
                    {k: cv for k, cv in r.items() if k != "attempts"}
                    | {"attempts": r.get("attempts", [])}
                    for r in vr["cases"]
                ]}
                for vr in all_variant_results
            ],
        }
        out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(f"\nFull results: {out_path}")


if __name__ == "__main__":
    main()
