"""
OPEN-57: the composed loop, end-to-end, no oracle labels.

See OPEN-57-precommit.md. Per case:
  mutate -> diff -> derive entry points -> (cached) spec+testgen+filter ->
  detect -> localize (learned, LOO) -> repair (top-2) -> loop-verify -> score.

Usage: python -m testfix.open57_loop
"""

import ast
import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent

from testfix.extractor import _extract_function_source
from testfix.retriever import retrieve_helpers
from testfix.retriever_bm25 import build_corpus as bm25_build, build_query
from testfix.retriever_embedding import build_corpus as emb_build
from testfix.localizer_bench import _build_pool
from testfix.localizer_learned import (
    _apply_scaler, _build_matrices, _feature_vector, _fit_scaler, _train,
)
from testfix.open55b_testgen import _call_model, _clear_pyc, _load_seeds
from testfix.open55b_filter_analysis import _run_pytest_verbose, _split_test_functions
from testfix.open56_evidence import _extract_code
from testfix.open56_extract import _build_extractor_prompt
from testfix.arm_b3_variants import _build_repair_prompt

MODEL = "gpt-4.1-mini"
MAX_ENTRY_POINTS = 4
MAX_LOCALIZER_CANDIDATES = 2

_STATUS_CONSTANTS = (ROOT / "app/db/status.py").read_text(encoding="utf-8")


# ── static call graph over app/ ────────────────────────────────────────────────

def _build_call_graph() -> tuple[dict[str, set[str]], dict[str, str]]:
    """Returns (callers_of: name -> set of caller names, def_file: name -> rel path)."""
    calls: dict[str, set[str]] = {}     # fn -> names it calls
    def_file: dict[str, str] = {}
    for p in sorted((ROOT / "app").rglob("*.py")):
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        rel = str(p.relative_to(ROOT)).replace("\\", "/")
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                def_file.setdefault(node.name, rel)
                called = {
                    n.func.id for n in ast.walk(node)
                    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                }
                calls.setdefault(node.name, set()).update(called)
    callers_of: dict[str, set[str]] = {}
    for fn, called in calls.items():
        for c in called:
            callers_of.setdefault(c, set()).add(fn)
    return callers_of, def_file


def _affected_entry_points(changed_fn: str, callers_of: dict, def_file: dict) -> list[tuple[str, str]]:
    """Public functions from which changed_fn is reachable, nearest-first.
    A changed public function is its own entry point at distance 0."""
    results: list[tuple[int, str]] = []
    seen = {changed_fn}
    frontier = [changed_fn]
    dist = 0
    if not changed_fn.startswith("_") and changed_fn in def_file:
        results.append((0, changed_fn))
    while frontier and len(results) < 12:
        nxt = []
        dist += 1
        for fn in frontier:
            for caller in sorted(callers_of.get(fn, ())):
                if caller in seen:
                    continue
                seen.add(caller)
                nxt.append(caller)
                if not caller.startswith("_") and caller in def_file:
                    results.append((dist, caller))
        frontier = nxt
    results.sort()
    return [(fn, def_file[fn]) for _, fn in results[:MAX_ENTRY_POINTS]]


# ── diff: which function changed (parent vs mutant file) ─────────────────────

def _changed_function(file_rel: str, parent_src: str, mutant_src: str) -> str | None:
    tree = ast.parse(parent_src)
    p_lines, m_lines = parent_src.splitlines(), mutant_src.splitlines()
    diff_idx = [i for i, (a, b) in enumerate(zip(p_lines, m_lines)) if a != b]
    if not diff_idx:
        return None
    line = diff_idx[0] + 1
    best = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.lineno <= line <= (node.end_lineno or node.lineno):
                if best is None or node.lineno > best.lineno:
                    best = node
    return best.name if best else None


# ── cached spec extraction + test generation per entry function ──────────────

_SPEC_CACHE: dict[str, str] = {}
_SUITE_CACHE: dict[str, dict] = {}   # fn -> {"header":..., "funcs": {name: src}}  (post-filter)


def _signature_of(fn: str, file_rel: str) -> str:
    src = _extract_function_source(ROOT / file_rel, fn) or f"def {fn}(...)"
    return src.splitlines()[0].removeprefix("def ").rstrip(":")


def _get_spec(fn: str, file_rel: str) -> str:
    if fn not in _SPEC_CACHE:
        evidence = {"E-code": _extract_code(fn, file_rel)}
        prompt = _build_extractor_prompt(fn, "E-code", evidence) if fn in _ec_sigs() else \
            _build_extractor_prompt_dyn(fn, file_rel, evidence["E-code"])
        spec, _ = _call_model(prompt, MODEL, max_tokens=900)
        _SPEC_CACHE[fn] = spec or "(extraction failed)"
    return _SPEC_CACHE[fn]


def _ec_sigs():
    from testfix.open56_extract import SIGNATURES
    return SIGNATURES


def _build_extractor_prompt_dyn(fn: str, file_rel: str, evidence: str) -> str:
    sig = _signature_of(fn, file_rel)
    return f"""You are writing a behavioral SPECIFICATION for a Python function, to be used by a separate test engineer who will write pytest tests from your spec alone (they will never see the implementation).

Function signature: {sig}

=== Evidence: the function's current trusted implementation source (including its helpers) ===
{evidence}

=== Your task ===
Write a compact behavioral specification (max 350 words) for `{fn}`. State as precisely as the evidence allows: the input schema (exact dict keys, fallback keys), return values per case, matching rules (case sensitivity, where keywords may appear), exact keyword/alias/threshold vocabularies enumerated in full, and boundary behavior. Do NOT invent behavior the evidence does not support; write "UNSPECIFIED: ..." where evidence is insufficient. Plain text only.
"""


def _gen_prompt(fn: str, file_rel: str, spec: str) -> str:
    module_dotpath = file_rel.replace("/", ".").removesuffix(".py")
    sig = _signature_of(fn, file_rel)
    return f"""You are a test engineer. Write pytest tests for the function below from its SPECIFICATION ONLY — you do not have access to the implementation.

=== Function ===
{sig}

Import as: from {module_dotpath} import {fn}

=== Specification ===
{spec}

=== Status constants (app/db/status.py) — import what you need ===
{_STATUS_CONSTANTS}

=== Your task ===
Write 3–6 pytest test functions that verify the SPECIFIED behaviour precisely, using realistic inputs and asserting SPECIFIC expected values (== or `is True`/`is False`). Cover edge cases the spec calls out (fallback keys, case-insensitivity, mid-sentence keywords, boundary counts, alias resolution). Where the spec marks an aspect UNSPECIFIED, do NOT test it. Do NOT directly call private helpers. Return ONLY valid Python code, no markdown fences.
"""


_SUITE_CACHE_PATH: Path | None = None  # OPEN-59: persist suites for across-arm eval


def _get_filtered_suite(fn: str, file_rel: str) -> dict:
    """Generate (once) + filter on parent. Returns {'header', 'funcs'} of survivors."""
    if fn in _SUITE_CACHE:
        return _SUITE_CACHE[fn]
    if _SUITE_CACHE_PATH and _SUITE_CACHE_PATH.exists():
        disk = json.loads(_SUITE_CACHE_PATH.read_text(encoding="utf-8"))
        if fn in disk:
            _SUITE_CACHE[fn] = disk[fn]
            return _SUITE_CACHE[fn]
    spec = _get_spec(fn, file_rel)
    code, _ = _call_model(_gen_prompt(fn, file_rel, spec), MODEL, max_tokens=2000)
    if not code:
        _SUITE_CACHE[fn] = {"header": "", "funcs": {}}
        return _SUITE_CACHE[fn]
    # run on parent, keep passing functions
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", prefix=f"o57_{fn}_p_", dir=ROOT / "testfix",
        delete=False, encoding="utf-8",
    ) as f:
        f.write(code)
        tmp = Path(f.name)
    try:
        outcomes = _run_pytest_verbose(tmp)
    finally:
        tmp.unlink(missing_ok=True)
    header, funcs = _split_test_functions(code)
    survivors = {n: s for n, s in funcs.items() if outcomes.get(n) == "passed"}
    _SUITE_CACHE[fn] = {"header": header, "funcs": survivors}
    if _SUITE_CACHE_PATH:
        disk = (json.loads(_SUITE_CACHE_PATH.read_text(encoding="utf-8"))
                if _SUITE_CACHE_PATH.exists() else {})
        disk[fn] = _SUITE_CACHE[fn]
        _SUITE_CACHE_PATH.write_text(json.dumps(disk), encoding="utf-8")
    return _SUITE_CACHE[fn]


# ── pytest helpers ────────────────────────────────────────────────────────────

def _run_suite(header: str, funcs: dict, label: str) -> tuple[bool, dict, str]:
    """Run suite; returns (all_passed, per_function_outcomes, raw_output)."""
    if not funcs:
        return True, {}, ""
    code = header + "".join(funcs.values())
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", prefix=f"o57_{label}_", dir=ROOT / "testfix",
        delete=False, encoding="utf-8",
    ) as f:
        f.write(code)
        tmp = Path(f.name)
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", str(tmp), "-v", "--tb=short", "--no-header"],
            capture_output=True, text=True, cwd=ROOT,
        )
        outcomes = {}
        for line in (result.stdout + result.stderr).splitlines():
            m = re.match(r".*::(\w+)(?:\[.*\])?\s+(PASSED|FAILED|ERROR)", line)
            if m:
                nm, st = m.group(1), m.group(2)
                if outcomes.get(nm) != "failed":
                    outcomes[nm] = "passed" if st == "PASSED" else "failed"
        return result.returncode == 0, outcomes, result.stdout + result.stderr
    finally:
        tmp.unlink(missing_ok=True)


def _run_human_test(test_id: str) -> bool:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", test_id, "--tb=no", "-q", "--no-header"],
        capture_output=True, text=True, cwd=ROOT,
    )
    return result.returncode == 0


# ── localizer ─────────────────────────────────────────────────────────────────

def _load_training(exclude_case: str) -> list[dict]:
    examples = []
    for line in (ROOT / "testfix/localizer_training.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        if d["case_id"] != exclude_case:
            examples.append(d)
    return examples


def _localize(case_id: str, entry_fn: str, entry_file: str,
              failing_src: str, failing_name: str, pytest_out: str,
              emb_index, bm25_index) -> list[dict]:
    """Returns ranked candidate list (dicts with function_name, file_path, source)."""
    pool = _build_pool(
        entry_fn, entry_file, emb_index, bm25_index, build_query,
        retrieve_helpers, failing_src, "", failing_name, pytest_out,
    )
    query_text = build_query(failing_src, "", failing_name, pytest_out)
    entry_base = entry_file.replace("\\", "/").split("/")[-1]
    for c in pool:
        c["name_in_query"] = c["function_name"] in query_text
        c["starts_with_underscore"] = c["function_name"].startswith("_")
        c["same_file_as_entry"] = c["file_path"].endswith(entry_base)
        c["is_true_B"] = False  # unused at inference

    train = _load_training(case_id)
    X, y = _build_matrices(train)
    means, stds = _fit_scaler(X)
    w = _train(_apply_scaler(X, means, stds), y)

    feats = np.array([_feature_vector(c) for c in pool])
    scores = _apply_scaler(feats, means, stds) @ w
    order = np.argsort(-scores)
    return [pool[i] for i in order]


# ── repair ────────────────────────────────────────────────────────────────────

def _attempt_repair(candidate: dict, entry_src: str, failing_src: str, pytest_out: str) -> str | None:
    prompt = _build_repair_prompt(
        failing_src, entry_src, candidate["function_name"], candidate["source"], pytest_out[-2000:],
    )
    fixed, _ = _call_model(prompt, MODEL, max_tokens=1200)
    if fixed and (fixed.startswith("def ") or fixed.startswith("async def ")):
        return fixed
    return None


# ── OPEN-60 Leg 2: deployable guards (all label-free) ─────────────────────────

def _guard_check(fixed: str, cand_name: str, pre_file_src: str, post_file_src: str) -> str | None:
    """Returns None if all guards pass, else the failing guard's name."""
    # G1: def-name guard — repair output's top-level def must match candidate
    try:
        fixed_tree = ast.parse(fixed)
    except SyntaxError:
        return "G1_syntax"
    top_defs = [n for n in fixed_tree.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    if len(top_defs) != 1 or top_defs[0].name != cand_name:
        return "G1_def_name"

    try:
        pre_tree = ast.parse(pre_file_src)
        post_tree = ast.parse(post_file_src)
    except SyntaxError:
        return "G2_syntax"

    def _top_funcs(tree):
        return {n.name: ast.unparse(n) for n in tree.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}

    pre_funcs, post_funcs = _top_funcs(pre_tree), _top_funcs(post_tree)

    # G3: duplicate-def lint
    post_names = [n.name for n in post_tree.body
                  if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    if len(post_names) != len(set(post_names)):
        return "G3_duplicate_def"

    # G2: diff confinement — only the candidate function may differ
    if set(pre_funcs) != set(post_funcs):
        return "G2_func_set_changed"
    for name in pre_funcs:
        if name != cand_name and pre_funcs[name] != post_funcs[name]:
            return "G2_other_func_changed"
    return None


# ── main loop ─────────────────────────────────────────────────────────────────

def main(out_name: str = "open57_results.json",
         priors: dict[str, float] | None = None,
         beta: float = 0.0,
         only_cases: set[str] | None = None,
         suite_cache: str | None = None,
         guards: bool = False,
         differential: bool = False) -> None:
    """priors/beta: OPEN-59 credit-assignment injection. beta=0 => identical
    behavior to the original loop (episode-collection mode). suite_cache:
    persist/reuse generated suites so across-arm evals share detection."""
    global _SUITE_CACHE_PATH
    if suite_cache:
        _SUITE_CACHE_PATH = ROOT / "testfix" / suite_cache
    seeds = _load_seeds()
    if only_cases:
        seeds = [s for s in seeds if s["case_id"] in only_cases]
    callers_of, def_file = _build_call_graph()

    print("Building retrieval indexes on parent codebase...")
    emb_index = emb_build()
    bm25_index = bm25_build()
    print(f"  corpus: {emb_index.size} functions")

    results = []
    for seed in seeds:
        case_id = seed["case_id"]
        target_path = ROOT / seed["target_file"]
        parent_src = target_path.read_text(encoding="utf-8")

        fn_src = _extract_function_source(target_path, seed["target_function"])
        mutated_fn = fn_src.replace(seed["original_snippet"], seed["mutated_snippet"], 1)
        mutant_src = parent_src.replace(fn_src, mutated_fn, 1)

        record = {"case_id": case_id, "stage": None, "loop_success": False,
                  "ground_truth": False, "entry_points": [], "detected_by": None,
                  "localizer_top": [], "repaired_fn": None,
                  "attempts": []}  # OPEN-59: [(candidate_fn, verified bool), ...]

        # The loop derives the changed function from the diff (no seed label used)
        changed = _changed_function(seed["target_file"], parent_src, mutant_src)
        if not changed:
            record["stage"] = "diff_failed"
            results.append(record); print(f"[{case_id}] diff_failed"); continue

        entries = _affected_entry_points(changed, callers_of, def_file)
        record["entry_points"] = [e[0] for e in entries]
        if not entries:
            record["stage"] = "no_entry_points"
            results.append(record); print(f"[{case_id}] no_entry_points"); continue

        # Build/cache filtered suites on the PARENT (before mutating disk)
        suites = {fn: _get_filtered_suite(fn, file) for fn, file in entries}

        # OPEN-61: differential corpus + parent outputs (computed on PARENT state)
        # OPEN-61b: determinism screen — corpus run twice on parent, unstable
        # inputs dropped; fn excluded entirely when <5 stable inputs remain.
        diff_parent: dict[str, tuple[str, list]] = {}
        if differential:
            from testfix.open61_differential import get_corpus, screen_corpus
            for fn, file in entries:
                dotpath = file.replace("/", ".").replace("\\", ".").removesuffix(".py")
                parent_fn_src = _extract_function_source(ROOT / file, fn) or ""
                corpus = get_corpus(fn, _signature_of(fn, file), _call_model, parent_fn_src)
                stable_corpus, p_out = screen_corpus(dotpath, fn, corpus)
                diff_parent[fn] = (dotpath, stable_corpus, p_out)

        # Mutate on disk
        target_path.write_text(mutant_src, encoding="utf-8")
        _clear_pyc(target_path)
        repaired_file: Path | None = None
        repaired_original: str | None = None
        try:
            # DETECTION: run each entry's survivors on mutant
            failing = None  # (entry_fn, entry_file, failing_name, failing_src, pytest_out)
            for fn, file in entries:
                suite = suites[fn]
                if not suite["funcs"]:
                    continue
                ok, outcomes, out = _run_suite(suite["header"], suite["funcs"], f"{case_id}_{fn}_det")
                if not ok:
                    fail_name = next(
                        (n for n, st in outcomes.items() if st == "failed"),
                        next(iter(suite["funcs"])),  # collection error: no per-test line
                    )
                    failing = (fn, file, fail_name, suite["funcs"][fail_name], out)
                    break
            if failing is None:
                record["stage"] = "missed_detection"
                results.append(record); print(f"[{case_id}] missed_detection"); continue
            # (amendment 1: collection-level failures fall back to first test fn)

            entry_fn, entry_file, fail_name, fail_src, pytest_out = failing
            record["detected_by"] = f"{entry_fn}::{fail_name}"

            # LOCALIZATION (learned, LOO over past episodes)
            ranked = _localize(case_id, entry_fn, entry_file, fail_src, fail_name,
                               pytest_out, emb_index, bm25_index)
            # OPEN-59: blend learned prior into candidate ordering (beta=0 => no-op)
            if priors and beta:
                base = {c["function_name"]: -i for i, c in enumerate(ranked)}
                ranked.sort(key=lambda c: -(base[c["function_name"]]
                                            + beta * priors.get(c["function_name"], 0.0)))
            record["localizer_top"] = [c["function_name"] for c in ranked[:3]]
            entry_src = _extract_function_source(ROOT / entry_file, entry_fn) or ""

            # REPAIR: top-2 pool candidates + the entry function itself
            # (amendment 2: a changed PUBLIC function is its own entry point;
            #  _build_pool excludes the entry, so it must be re-added here —
            #  matches B3e's "entry-point or one of the candidates" design)
            entry_candidate = {
                "function_name": entry_fn,
                "file_path": entry_file,
                "source": entry_src,
            }
            candidates = ranked[:MAX_LOCALIZER_CANDIDATES] + [entry_candidate]
            success = False
            for cand in candidates:
                fixed = _attempt_repair(cand, entry_src, fail_src, pytest_out)
                if not fixed:
                    record["attempts"].append([cand["function_name"], False])
                    continue
                cand_path = ROOT / cand["file_path"]
                cand_file_src = cand_path.read_text(encoding="utf-8")
                cur_src = _extract_function_source(cand_path, cand["function_name"])
                if not cur_src or cur_src not in cand_file_src:
                    continue
                new_file_src = cand_file_src.replace(cur_src, fixed.rstrip() + "\n", 1)
                if guards:
                    g = _guard_check(fixed, cand["function_name"], cand_file_src, new_file_src)
                    if g is not None:
                        record["attempts"].append([cand["function_name"], False])
                        record.setdefault("guard_rejections", []).append(
                            [cand["function_name"], g])
                        continue
                cand_path.write_text(new_file_src, encoding="utf-8")
                _clear_pyc(cand_path)

                # LOOP VERIFICATION: every entry's survivor suite passes
                all_ok = True
                for fn2, _file2 in entries:
                    s2 = suites[fn2]
                    if not s2["funcs"]:
                        continue
                    ok2, _, _ = _run_suite(s2["header"], s2["funcs"], f"{case_id}_{fn2}_ver")
                    if not ok2:
                        all_ok = False
                        break
                # OPEN-61: differential-vs-parent check (after suite verification)
                if all_ok and differential:
                    from testfix.open61_differential import run_outputs, diverges
                    for fn3, (dotpath3, corpus3, p_out3) in diff_parent.items():
                        r_out3 = run_outputs(dotpath3, fn3, corpus3)
                        if diverges(p_out3, r_out3):
                            all_ok = False
                            record.setdefault("diff_rejections", []).append(
                                [cand["function_name"], fn3])
                            # scoring-only: oracle precision (never shown to loop)
                            record.setdefault("diff_rejection_human", []).append(
                                [cand["function_name"], _run_human_test(seed["test_id"])])
                            break

                record["attempts"].append([cand["function_name"], all_ok])
                if all_ok:
                    success = True
                    repaired_file = cand_path
                    repaired_original = cand_file_src
                    record["repaired_fn"] = cand["function_name"]
                    break
                # revert this attempt
                cand_path.write_text(cand_file_src, encoding="utf-8")
                _clear_pyc(cand_path)

            if not success:
                record["stage"] = "repair_failed"
                results.append(record)
                print(f"[{case_id}] repair_failed  (detected by {record['detected_by']}, "
                      f"top3={record['localizer_top']})")
                continue

            record["loop_success"] = True
            # GROUND TRUTH (scoring only)
            record["ground_truth"] = _run_human_test(seed["test_id"])
            record["stage"] = "success" if record["ground_truth"] else "false_success"
            results.append(record)
            print(f"[{case_id}] loop=SUCCESS  ground_truth={record['ground_truth']}  "
                  f"repaired={record['repaired_fn']}  (true B={seed['target_function']})")
        finally:
            # restore: repaired file first (if different), then the mutated target
            if repaired_file is not None and repaired_file != target_path:
                repaired_file.write_text(repaired_original, encoding="utf-8")
                _clear_pyc(repaired_file)
            target_path.write_text(parent_src, encoding="utf-8")
            _clear_pyc(target_path)

    # ── summary ──
    n = len(results)
    gt = sum(r["ground_truth"] for r in results)
    loop_claims = sum(r["loop_success"] for r in results)
    false_succ = sum(1 for r in results if r["loop_success"] and not r["ground_truth"])
    from collections import Counter
    stages = Counter(r["stage"] for r in results)

    print("\n" + "=" * 70)
    print(f"OPEN-57 COMPOSED LOOP  n={n}")
    print("=" * 70)
    print(f"  ground-truth success : {gt}/{n} = {gt/n:.0%}")
    print(f"  loop-claimed success : {loop_claims}/{n}")
    print(f"  false successes      : {false_succ}")
    print(f"  stage attrition      : {dict(stages)}")
    verdict = "GREEN" if gt >= 8 else ("YELLOW" if gt >= 5 else "RED")
    print(f"  S4 precommit         : {verdict}  (GREEN>=8/20, YELLOW 5-7, RED<=4)")

    out = ROOT / "testfix" / out_name
    out.write_text(json.dumps({"model": MODEL, "results": results}, indent=2), encoding="utf-8")
    print(f"\nResults: {out}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="open57_results.json")
    parser.add_argument("--priors", default=None, help="JSON file of {fn: prior}")
    parser.add_argument("--beta", type=float, default=0.0)
    parser.add_argument("--cases", default=None, help="comma-separated case_ids")
    parser.add_argument("--suite-cache", default=None, help="suite cache file name in testfix/")
    parser.add_argument("--guards", action="store_true", help="OPEN-60 G1-G3 repair guards")
    parser.add_argument("--differential", action="store_true", help="OPEN-61 differential-vs-parent")
    args = parser.parse_args()
    priors = None
    if args.priors:
        priors = json.loads((ROOT / args.priors).read_text(encoding="utf-8"))
    only = set(args.cases.split(",")) if args.cases else None
    main(out_name=args.out, priors=priors, beta=args.beta, only_cases=only,
         suite_cache=args.suite_cache, guards=args.guards, differential=args.differential)
