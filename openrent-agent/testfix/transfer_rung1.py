"""
Transfer rung 1: the hardened loop, ported to python-tabulate.

Pipeline UNCHANGED from CTRL-GDS (OPEN-61b): spec extraction (E-code) ->
test generation -> parent filter -> detection -> learned localization
(OpenRent-trained weights, applied unchanged) -> repair top-2+entry ->
G1-G3 guards -> differential-vs-parent -> determinism screen -> suite
verification. Necessary de-OpenRent-izations only (logged in precommit):
status-constants prompt section dropped; corpus prompt domain examples
removed (parent-source conditioning carries the domain).

Ground truth (scoring only, never shown to the loop): the repo's own pytest
suite passes on the repaired code.

Usage: python -m testfix.transfer_rung1
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

OR_ROOT = Path(__file__).resolve().parent.parent          # OpenRent root (for key + training data)
REPO = Path("D:/transfer-rung1/python-tabulate")
MODULE_FILE = REPO / "tabulate/__init__.py"
MODULE_DOTPATH = "tabulate"
MUTATIONS = Path(__file__).resolve().parent / "transfer_mutations.json"
SUITE_CACHE = Path(__file__).resolve().parent / "transfer_suites.json"
CORPUS_CACHE = Path(__file__).resolve().parent / "transfer_corpus.json"
OUT = Path(__file__).resolve().parent / "transfer_rung1_results.json"

MODEL = "gpt-4.1-mini"
MAX_ENTRY_POINTS = 4
MAX_LOCALIZER_CANDIDATES = 2

from testfix.open55b_testgen import _call_model           # OpenAI glue (key via app.config)
from testfix.open55b_filter_analysis import _split_test_functions
from testfix.open57_loop import _guard_check
from testfix.arm_b3_variants import _build_repair_prompt
from testfix.localizer_learned import (
    _apply_scaler, _build_matrices, _feature_vector, _fit_scaler, _train,
)
from testfix.retriever_embedding import EmbeddingIndex
from testfix.retriever_bm25 import BM25Index
from testfix.retriever_bm25 import build_query


# ── module model ──────────────────────────────────────────────────────────────

def _module_functions(src: str) -> dict[str, tuple[int, int, str]]:
    tree = ast.parse(src)
    lines = src.splitlines(keepends=True)
    return {
        n.name: (n.lineno, n.end_lineno, "".join(lines[n.lineno - 1: n.end_lineno]))
        for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _call_edges(funcs: dict) -> dict[str, set[str]]:
    """RUNG 1b fix 1: edges include first-class function REFERENCES (any
    ast.Name matching a module function), not just ast.Call — catches
    TableFormat-style dispatch where helpers are stored as values."""
    edges: dict[str, set[str]] = {}
    names = set(funcs)
    for fn, (_, _, src) in funcs.items():
        referenced = {
            n.id for n in ast.walk(ast.parse(src))
            if isinstance(n, ast.Name)
        }
        edges[fn] = (referenced & names) - {fn}
    return edges


def _expand_edges_through_module_refs(edges: dict, parent_src: str, funcs: dict) -> dict:
    """fn -> module-level container (e.g. _table_formats) -> helper functions."""
    mod_refs = _module_level_refs(parent_src, funcs)
    names = set(funcs)
    out = {}
    for fn, (_, _, src) in funcs.items():
        referenced = {n.id for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Name)}
        expanded = set(edges.get(fn, set()))
        for t in referenced:
            if t in mod_refs:
                expanded |= mod_refs[t]
        out[fn] = (expanded & names) - {fn}
    return out


def _module_level_refs(parent_src: str, funcs: dict) -> dict[str, set[str]]:
    """Functions referenced in MODULE-LEVEL code (e.g. the _table_formats dict
    of TableFormat structures). Treated as referenced-by any public function
    that reads the containing module-level name. Conservative approximation:
    map each module-level assignment target to the functions it references."""
    tree = ast.parse(parent_src)
    names = set(funcs)
    out: dict[str, set[str]] = {}
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = []
            if isinstance(node, ast.Assign):
                targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            elif isinstance(node.target, ast.Name):
                targets = [node.target.id]
            refs = {
                n.id for n in ast.walk(node) if isinstance(n, ast.Name)
            } & names
            for t in targets:
                if refs:
                    out[t] = refs
    return out


def _transitive_callees(fn: str, edges: dict[str, set[str]]) -> set[str]:
    seen, frontier = set(), [fn]
    while frontier:
        cur = frontier.pop()
        for c in edges.get(cur, ()):
            if c not in seen:
                seen.add(c)
                frontier.append(c)
    return seen


def _entry_points(changed: str, funcs: dict, edges: dict) -> list[str]:
    callers: dict[str, set[str]] = {}
    for f, called in edges.items():
        for c in called:
            callers.setdefault(c, set()).add(f)
    results = []
    if not changed.startswith("_"):
        results.append((0, changed))
    seen, frontier, dist = {changed}, [changed], 0
    while frontier:
        nxt = []
        dist += 1
        for fn in frontier:
            for caller in sorted(callers.get(fn, ())):
                if caller in seen:
                    continue
                seen.add(caller)
                nxt.append(caller)
                if not caller.startswith("_"):
                    results.append((dist, caller))
        frontier = nxt
    results.sort()
    return [fn for _, fn in results[:MAX_ENTRY_POINTS]]


def _changed_function(parent_src: str, mutant_src: str, funcs: dict) -> str | None:
    p, m = parent_src.splitlines(), mutant_src.splitlines()
    diff = [i for i, (a, b) in enumerate(zip(p, m)) if a != b]
    if not diff:
        return None
    line = diff[0] + 1
    for fn, (start, end, _) in funcs.items():
        if start <= line <= end:
            return fn
    return None


def _clear_pyc() -> None:
    cache = MODULE_FILE.parent / "__pycache__"
    if cache.exists():
        for p in cache.glob("*.pyc"):
            try:
                p.unlink()
            except OSError:
                pass


# ── pytest helpers (cwd = foreign repo) ───────────────────────────────────────

def _run_pytest_file(path: Path) -> tuple[bool, dict, str]:
    r = subprocess.run(
        [sys.executable, "-m", "pytest", str(path), "-v", "--tb=short", "--no-header"],
        capture_output=True, text=True, cwd=REPO, timeout=300,
    )
    out = r.stdout + r.stderr
    outcomes: dict[str, str] = {}
    for line in out.splitlines():
        m = re.match(r".*::(\w+)(?:\[.*\])?\s+(PASSED|FAILED|ERROR)", line)
        if m:
            nm, st = m.group(1), m.group(2)
            if outcomes.get(nm) != "failed":
                outcomes[nm] = "passed" if st == "PASSED" else "failed"
    return r.returncode == 0, outcomes, out


def _run_repo_suite() -> bool:
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "test/", "-q", "--no-header", "--tb=no"],
        capture_output=True, text=True, cwd=REPO, timeout=300,
    )
    return r.returncode == 0


# ── spec extraction + test generation (prompts unchanged modulo logged ports) ──

def _extract_code_evidence(fn: str, funcs: dict, edges: dict) -> str:
    parts = [f"# === {fn} (tabulate/__init__.py) ===\n{funcs[fn][2]}"]
    for h in sorted(edges.get(fn, ())):
        parts.append(f"# === helper {h} ===\n{funcs[h][2]}")
    return "\n\n".join(parts)


def _signature_of(fn: str, funcs: dict) -> str:
    return funcs[fn][2].splitlines()[0].removeprefix("def ").rstrip(":")


def _spec_prompt(fn: str, sig: str, evidence: str) -> str:
    return f"""You are writing a behavioral SPECIFICATION for a Python function, to be used by a separate test engineer who will write pytest tests from your spec alone (they will never see the implementation).

Function signature: {sig}

=== Evidence: the function's current trusted implementation source (including its helpers) ===
{evidence}

=== Your task ===
Write a compact behavioral specification (max 350 words) for `{fn}`. State as precisely as the evidence allows: the input schema (parameter types, accepted values), return values per case, matching/formatting rules, exact option/format vocabularies enumerated in full when visible, and boundary behavior. Do NOT invent behavior the evidence does not support; write "UNSPECIFIED: ..." where evidence is insufficient. Plain text only.
"""


def _gen_prompt(fn: str, sig: str, spec: str) -> str:
    return f"""You are a test engineer. Write pytest tests for the function below from its SPECIFICATION ONLY — you do not have access to the implementation.

=== Function ===
{sig}

Import as: from {MODULE_DOTPATH} import {fn}

=== Specification ===
{spec}

=== Your task ===
Write 3–6 pytest test functions that verify the SPECIFIED behaviour precisely, using realistic inputs and asserting SPECIFIC expected values (== or `is True`/`is False`). Cover edge cases the spec calls out (option vocabularies, boundary counts, formatting rules). Where the spec marks an aspect UNSPECIFIED, do NOT test it. Do NOT directly call private helpers. Return ONLY valid Python code, no markdown fences.
"""


_SUITES: dict[str, dict] = {}


def _gen_one_shard(fn: str, sig: str, evidence: str, shard_tag: str) -> dict:
    """One spec+gen+filter pass. Returns {'header', 'funcs'} of survivors."""
    spec, _ = _call_model(_spec_prompt(fn, sig, evidence), MODEL, max_tokens=900)
    code, _ = _call_model(_gen_prompt(fn, sig, spec or ""), MODEL, max_tokens=2000)
    if not code:
        return {"header": "", "funcs": {}}
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", prefix=f"_o62gen_{shard_tag}_", dir=REPO,
        delete=False, encoding="utf-8",
    ) as f:
        f.write(code)
        tmp = Path(f.name)
    try:
        _, outcomes, _ = _run_pytest_file(tmp)
    finally:
        tmp.unlink(missing_ok=True)
    header, fns = _split_test_functions(code)
    survivors = {n: s for n, s in fns.items() if outcomes.get(n) == "passed"}
    return {"header": header, "funcs": survivors}


def _get_suite(fn: str, funcs: dict, edges: dict) -> dict:
    """RUNG 1b fix 2: suite budget scales with the entry's direct-helper
    surface. >8 helpers -> shard into groups of <=6, one spec+gen pass per
    shard (entry source + that shard's helpers as evidence), merge survivors.
    Shards capped at 12."""
    if fn in _SUITES:
        return _SUITES[fn]
    disk = json.loads(SUITE_CACHE.read_text(encoding="utf-8")) if SUITE_CACHE.exists() else {}
    if fn in disk:
        _SUITES[fn] = disk[fn]
        return disk[fn]

    sig = _signature_of(fn, funcs)
    helpers = sorted(edges.get(fn, ()))
    if len(helpers) <= 8:
        suite = _gen_one_shard(fn, sig, _extract_code_evidence(fn, funcs, edges), fn[:12])
    else:
        groups = [helpers[i:i + 6] for i in range(0, len(helpers), 6)][:12]
        header_lines: list[str] = []
        seen_lines: set[str] = set()
        merged_funcs: dict[str, str] = {}
        for gi, group in enumerate(groups):
            evidence = "\n\n".join(
                [f"# === {fn} (tabulate/__init__.py) ===\n{funcs[fn][2]}"]
                + [f"# === helper {h} ===\n{funcs[h][2]}" for h in group]
            )
            shard = _gen_one_shard(fn, sig, evidence, f"{fn[:8]}_s{gi}")
            for line in shard["header"].splitlines(keepends=True):
                key = line.strip()
                if key and key not in seen_lines:
                    seen_lines.add(key)
                    header_lines.append(line)
                elif not key:
                    header_lines.append(line)
            for name, src in shard["funcs"].items():
                merged_funcs[f"{name}_s{gi}"] = src.replace(
                    f"def {name}(", f"def {name}_s{gi}(", 1)
            print(f"    [suite {fn} shard {gi+1}/{len(groups)}] "
                  f"{len(shard['funcs'])} survivors")
        suite = {"header": "".join(header_lines), "funcs": merged_funcs}
        # post-merge validation on parent: header merging can interact;
        # drop any test that no longer passes
        ok, outcomes, _ = _run_suite_dict(suite, f"{fn[:8]}_merged")
        if not ok:
            suite["funcs"] = {n: s for n, s in suite["funcs"].items()
                              if outcomes.get(n) == "passed"}
        print(f"    [suite {fn}] merged: {len(suite['funcs'])} tests")

    _SUITES[fn] = suite
    disk[fn] = suite
    SUITE_CACHE.write_text(json.dumps(disk), encoding="utf-8")
    return suite


def _run_suite_dict(suite: dict, label: str) -> tuple[bool, dict, str]:
    if not suite["funcs"]:
        return True, {}, ""
    code = suite["header"] + "".join(suite["funcs"].values())
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", prefix=f"_o62_{label}_", dir=REPO,
        delete=False, encoding="utf-8",
    ) as f:
        f.write(code)
        tmp = Path(f.name)
    try:
        return _run_pytest_file(tmp)
    finally:
        tmp.unlink(missing_ok=True)


# ── localization (OpenRent-trained weights, unchanged) ───────────────────────

def _train_weights():
    examples = []
    for line in (OR_ROOT / "testfix/localizer_training.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            examples.append(json.loads(line))
    X, y = _build_matrices(examples)
    means, stds = _fit_scaler(X)
    w = _train(_apply_scaler(X, means, stds), y)
    return w, means, stds


def _build_indexes(funcs: dict):
    emb = EmbeddingIndex()
    bm = BM25Index()
    for fn, (_, _, src) in funcs.items():
        emb.add(fn, "tabulate/__init__.py", src)
        bm.add(fn, "tabulate/__init__.py", src)
    emb.build()
    bm.build()
    return emb, bm


def _localize(entry_fn: str, funcs: dict, edges: dict,
              fail_src: str, fail_name: str, pytest_out: str,
              emb, bm, w, means, stds) -> list[dict]:
    query_text = build_query(fail_src, "", fail_name, pytest_out)
    emb_results = emb.query(query_text, top_k=10, exclude_function=entry_fn)
    bm_all = bm.query(query_text, top_k=bm.size, exclude_function=entry_fn)
    bm_rank = {r["function_name"]: r["rank"] for r in bm_all}
    bm_score = {r["function_name"]: r["score"] for r in bm_all}
    helpers = sorted(edges.get(entry_fn, ()))
    cg_rank = {h: i + 1 for i, h in enumerate(helpers)}

    pool: dict[str, dict] = {}
    for r in emb_results:
        n = r["function_name"]
        pool[n] = {
            "function_name": n, "file_path": "tabulate/__init__.py",
            "source": r["source"], "emb_rank": r["rank"], "emb_score": r["score"],
            "bm25_rank": bm_rank.get(n), "bm25_score": bm_score.get(n, 0.0),
            "in_call_graph": n in cg_rank, "call_graph_rank": cg_rank.get(n),
        }
    for h in helpers:
        if h not in pool and h != entry_fn:
            pool[h] = {
                "function_name": h, "file_path": "tabulate/__init__.py",
                "source": funcs[h][2], "emb_rank": None, "emb_score": None,
                "bm25_rank": bm_rank.get(h), "bm25_score": bm_score.get(h, 0.0),
                "in_call_graph": True, "call_graph_rank": cg_rank[h],
            }
    cands = list(pool.values())
    for c in cands:
        c["name_in_query"] = c["function_name"] in query_text
        c["starts_with_underscore"] = c["function_name"].startswith("_")
        c["same_file_as_entry"] = True
    feats = np.array([_feature_vector(c) for c in cands])
    scores = _apply_scaler(feats, means, stds) @ w
    order = np.argsort(-scores)
    return [cands[i] for i in order]


# ── differential (corpus prompt de-domained — logged port) ────────────────────

def _corpus_prompt(fn: str, sig: str, parent_source: str) -> str:
    return f"""Generate a differential-testing input corpus for this Python function:

    {sig}

=== Trusted reference implementation (generate inputs that exercise EVERY branch, key lookup, comparison, and table entry visible below) ===
{parent_source}

Return a JSON array of EXACTLY 20 strings. Each string is a Python expression
evaluating to the COMPLETE argument tuple for one call. Infer each parameter's
type from the signature and the reference implementation, e.g.:
  "([['a', 1], ['b', 2]],)"
  "([['x', 1.5]], ['col1', 'col2'], 'github')"

Coverage requirements: every branch and option/format value visible in the
reference, empty inputs, boundary counts, and inputs where branches DIFFER in
output. `datetime` and `timedelta` are available in the eval namespace.
Return ONLY the JSON array.
"""


_RUNNER = '''
import json, os, sys
sys.path.insert(0, os.getcwd())
from datetime import datetime as _dt, timedelta
module_path, fn_name, corpus_json = sys.argv[1], sys.argv[2], sys.argv[3]
inputs = json.loads(corpus_json)
import importlib
mod = importlib.import_module(module_path)
fn = getattr(mod, fn_name)
ns = {"datetime": _dt, "timedelta": timedelta}
out = []
for expr in inputs:
    try:
        args = eval(expr, ns)
        if not isinstance(args, tuple):
            args = (args,)
        out.append(repr(fn(*args)))
    except Exception as exc:
        out.append(f"EXC:{type(exc).__name__}:{exc}")
print(json.dumps(out))
'''


def _run_corpus(fn: str, inputs: list[str]) -> list[str] | None:
    if not inputs:
        return None
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", prefix="_o62run_", dir=REPO, delete=False, encoding="utf-8",
    ) as f:
        f.write(_RUNNER)
        runner = Path(f.name)
    try:
        r = subprocess.run(
            [sys.executable, str(runner), MODULE_DOTPATH, fn, json.dumps(inputs)],
            capture_output=True, text=True, cwd=REPO, timeout=120,
        )
        if r.returncode != 0:
            return None
        return json.loads(r.stdout.strip())
    except Exception:
        return None
    finally:
        runner.unlink(missing_ok=True)


def _get_corpus(fn: str, funcs: dict) -> list[str]:
    disk = json.loads(CORPUS_CACHE.read_text(encoding="utf-8")) if CORPUS_CACHE.exists() else {}
    if fn in disk:
        return disk[fn]
    raw, _ = _call_model(_corpus_prompt(fn, _signature_of(fn, funcs), funcs[fn][2]),
                         MODEL, max_tokens=2000)
    inputs: list[str] = []
    if raw:
        try:
            t = raw.strip()
            if t.startswith("```"):
                t = "\n".join(l for l in t.splitlines() if not l.strip().startswith("```"))
            inputs = json.loads(t)[:20]
        except Exception:
            inputs = []
    disk[fn] = inputs
    CORPUS_CACHE.write_text(json.dumps(disk, indent=2), encoding="utf-8")
    return inputs


def _screened_parent(fn: str, funcs: dict) -> tuple[list[str], list[str] | None]:
    corpus = _get_corpus(fn, funcs)
    o1 = _run_corpus(fn, corpus)
    o2 = _run_corpus(fn, corpus)
    if o1 is None or o2 is None:
        return [], None
    stable = [(i, a) for i, a, b in zip(corpus, o1, o2) if a == b]
    if len(stable) < 5:
        return [], None
    return [i for i, _ in stable], [a for _, a in stable]


# ── repair (RUNG 1b fix 3: locate-then-patch) ─────────────────────────────────

def _patch_prompt(fail_src: str, entry_src: str, cand_name: str,
                  cand_src: str, error: str) -> str:
    return (
        "You are fixing a Python bug. A test is failing.\n\n"
        f"FAILING TEST:\n{fail_src}\n\n"
        f"ENTRY-POINT FUNCTION (the function the test calls directly):\n{entry_src}\n"
        f"\nFUNCTION TO FIX ({cand_name}):\n{cand_src}\n\n"
        f"TEST ERROR:\n{error}\n\n"
        "Produce a MINIMAL patch to the function above. Reply in EXACTLY this format:\n"
        "<<<<SEARCH\n"
        "(one or more EXACT consecutive lines copied verbatim from the function)\n"
        "====\n"
        "(the replacement lines)\n"
        ">>>>\n"
        "The SEARCH text must appear exactly once in the function. Change as few "
        "lines as possible. No explanation outside the block."
    )


def _attempt_patch(cand: dict, entry_src: str, fail_src: str,
                   pytest_out: str) -> str | None:
    """Returns the candidate's NEW function source, or None."""
    raw, _ = _call_model(
        _patch_prompt(fail_src, entry_src, cand["function_name"],
                      cand["source"], pytest_out[-2000:]),
        MODEL, max_tokens=900)
    if not raw:
        return None
    m = re.search(r"<<<<SEARCH\n(.*?)\n====\n(.*?)\n?>>>>", raw, re.DOTALL)
    if not m:
        return None
    search, replace = m.group(1), m.group(2)
    cand_src = cand["source"]
    if cand_src.count(search) != 1:
        return None
    new_src = cand_src.replace(search, replace, 1)
    try:
        ast.parse(new_src)
    except SyntaxError:
        return None
    return new_src


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    mutations = json.loads(MUTATIONS.read_text(encoding="utf-8"))
    parent_src = MODULE_FILE.read_text(encoding="utf-8")
    funcs = _module_functions(parent_src)
    edges = _call_edges(funcs)
    edges = _expand_edges_through_module_refs(edges, parent_src, funcs)  # 1b fix 1

    print("Training localizer weights on OpenRent episodes (unchanged transfer)...")
    w, means, stds = _train_weights()
    print("Building retrieval indexes over tabulate functions...")
    emb, bm = _build_indexes(funcs)
    print(f"  corpus: {emb.size if hasattr(emb,'size') else len(funcs)} functions")

    results = []
    for mut in mutations:
        case_id = mut["case_id"]
        lines = parent_src.splitlines(keepends=True)
        idx = mut["lineno"] - 1
        assert lines[idx] == mut["original_line"], f"{case_id}: line drift"
        lines[idx] = mut["mutated_line"]
        mutant_src = "".join(lines)

        record = {"case_id": case_id, "true_fn": mut["function"],
                  "operator": mut["operator"], "stage": None,
                  "loop_success": False, "ground_truth": False,
                  "entry_points": [], "detected_by": None,
                  "localizer_top": [], "attempts": [], "repaired_fn": None}

        changed = _changed_function(parent_src, mutant_src, funcs)
        entries = _entry_points(changed, funcs, edges) if changed else []
        record["entry_points"] = entries
        if not entries:
            record["stage"] = "no_entry_points"
            results.append(record)
            print(f"[{case_id}] no_entry_points")
            continue

        suites = {fn: _get_suite(fn, funcs, edges) for fn in entries}
        diff_parent = {fn: _screened_parent(fn, funcs) for fn in entries}

        MODULE_FILE.write_text(mutant_src, encoding="utf-8")
        _clear_pyc()
        repaired_state: str | None = None
        try:
            failing = None
            for fn in entries:
                ok, outcomes, out = _run_suite_dict(suites[fn], f"{case_id}_{fn}")
                if not ok:
                    fail_name = next((n for n, st in outcomes.items() if st == "failed"),
                                     next(iter(suites[fn]["funcs"]), None))
                    if fail_name:
                        failing = (fn, fail_name, suites[fn]["funcs"][fail_name], out)
                        break
            if failing is None:
                record["stage"] = "missed_detection"
                results.append(record)
                print(f"[{case_id}] missed_detection  (true fn: {mut['function']})")
                continue

            entry_fn, fail_name, fail_src, pytest_out = failing
            record["detected_by"] = f"{entry_fn}::{fail_name}"
            ranked = _localize(entry_fn, funcs, edges, fail_src, fail_name,
                               pytest_out, emb, bm, w, means, stds)
            record["localizer_top"] = [c["function_name"] for c in ranked[:3]]
            entry_src = funcs[entry_fn][2]
            entry_cand = {"function_name": entry_fn, "file_path": "tabulate/__init__.py",
                          "source": entry_src}
            candidates = ranked[:MAX_LOCALIZER_CANDIDATES] + [entry_cand]

            success = False
            for cand in candidates:
                # patch against the CURRENT (mutant) source of the candidate
                cur_file = MODULE_FILE.read_text(encoding="utf-8")
                cur_funcs = _module_functions(cur_file)
                if cand["function_name"] not in cur_funcs:
                    record["attempts"].append([cand["function_name"], False])
                    continue
                cur_src = cur_funcs[cand["function_name"]][2]
                cand_live = dict(cand, source=cur_src)
                fixed = _attempt_patch(cand_live, entry_src, fail_src, pytest_out)
                if not fixed:
                    record["attempts"].append([cand["function_name"], False])
                    continue
                new_file = cur_file.replace(cur_src, fixed.rstrip() + "\n", 1)
                g = _guard_check(fixed, cand["function_name"], cur_file, new_file)
                if g is not None:
                    record["attempts"].append([cand["function_name"], False])
                    record.setdefault("guard_rejections", []).append(
                        [cand["function_name"], g])
                    continue
                MODULE_FILE.write_text(new_file, encoding="utf-8")
                _clear_pyc()

                all_ok = True
                for fn2 in entries:
                    ok2, _, _ = _run_suite_dict(suites[fn2], f"{case_id}_{fn2}_v")
                    if not ok2:
                        all_ok = False
                        break
                if all_ok:
                    for fn3 in entries:
                        sc, p_out = diff_parent[fn3]
                        r_out = _run_corpus(fn3, sc)
                        if p_out is not None and r_out is not None and p_out != r_out:
                            all_ok = False
                            record.setdefault("diff_rejections", []).append(
                                [cand["function_name"], fn3])
                            record.setdefault("diff_rejection_gt", []).append(
                                [cand["function_name"], _run_repo_suite()])
                            break

                record["attempts"].append([cand["function_name"], all_ok])
                if all_ok:
                    success = True
                    repaired_state = MODULE_FILE.read_text(encoding="utf-8")
                    record["repaired_fn"] = cand["function_name"]
                    break
                MODULE_FILE.write_text(cur_file, encoding="utf-8")
                _clear_pyc()

            if not success:
                record["stage"] = "repair_failed"
                results.append(record)
                print(f"[{case_id}] repair_failed  (true: {mut['function']}, "
                      f"top3: {record['localizer_top']})")
                continue

            record["loop_success"] = True
            record["ground_truth"] = _run_repo_suite()
            record["stage"] = "success" if record["ground_truth"] else "false_success"
            results.append(record)
            print(f"[{case_id}] loop=SUCCESS gt={record['ground_truth']} "
                  f"repaired={record['repaired_fn']} (true: {mut['function']})")
        finally:
            MODULE_FILE.write_text(parent_src, encoding="utf-8")
            _clear_pyc()

    # summary
    from collections import Counter
    n = len(results)
    gt = sum(r["ground_truth"] for r in results)
    fs = sum(1 for r in results if r["loop_success"] and not r["ground_truth"])
    det = sum(1 for r in results if r["detected_by"])
    loc3 = sum(1 for r in results if r["true_fn"] in r["localizer_top"])
    fr = sum(1 for r in results
             for _, gtv in (r.get("diff_rejection_gt") or []) if gtv)
    stages = Counter(r["stage"] for r in results)
    print("\n" + "=" * 70)
    print(f"TRANSFER RUNG 1  python-tabulate  n={n}")
    print("=" * 70)
    print(f"  detection            : {det}/{n}")
    print(f"  true fn in top-3     : {loc3}/{n}")
    print(f"  ground-truth success : {gt}/{n} = {gt/n:.0%}")
    print(f"  false successes      : {fs}")
    print(f"  false rejections     : {fr}")
    print(f"  stage attrition      : {dict(stages)}")
    band = ("GREEN" if (gt / n >= 0.25 and fs == 0) else
            "YELLOW" if ((gt / n >= 0.10 and fs == 0) or (gt / n >= 0.25 and fs <= 1)) else
            "RED")
    print(f"  precommit            : {band}  (GREEN>=25%+0FP, YELLOW>=10%+0FP or >=25%+<=1FP)")
    OUT.write_text(json.dumps({"model": MODEL, "repo": "python-tabulate",
                               "results": results}, indent=2), encoding="utf-8")
    print(f"\nResults: {OUT}")


if __name__ == "__main__":
    main()
