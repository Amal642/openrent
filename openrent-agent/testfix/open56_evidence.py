"""
OPEN-56 step 1: build extraction evidence bundles per entry function per arm.

Arms (per OPEN-56-precommit.md):
  E1     existing test files only (test_arm_a_* EXCLUDED)
  E2     runtime call traces only (captured while running the included tests)
  E3     comments + docstrings only
  E4     static usage only (AST call sites from app/, excluding tests/testfix)
  E-code original implementation (entry function + depth-1 helpers)

Output: testfix/open56_evidence.json
  {entry_func: {"E1": str, "E2": str, "E3": str, "E4": str, "E-code": str}}

Leakage rules enforced here:
  - tests/test_arm_a_*.py never read
  - testfix/ never read (except this harness's own outputs)
  - hand-authored SPECS never read
"""

import ast
import io
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

ENTRY_FUNCS: dict[str, str] = {
    "detect_stage": "app/ai/stages.py",
    "extract_viewing_datetime": "app/ai/stages.py",
    "detect_landlord_attitude": "app/ai/conversation_memory.py",
    "landlord_messages": "app/ai/conversation_memory.py",
    "latest_landlord_asked_for_phone": "app/ai/conversation_memory.py",
    "outbound_count": "app/ai/conversation_memory.py",
    "viewing_requested": "app/ai/conversation_memory.py",
    "phone_shared_state": "app/ai/conversation_memory.py",
    "get_conversation_style": "app/ai/personas.py",
    "should_share_phone_now": "app/ai/personas.py",
}


# ── E1: existing tests (arm suites excluded) ──────────────────────────────────

def _included_test_files() -> list[Path]:
    files = []
    for p in sorted((ROOT / "tests").glob("test_*.py")):
        if p.name.startswith("test_arm_a"):
            continue  # leakage rule 1
        files.append(p)
    return files


def _extract_test_functions_mentioning(name: str) -> str:
    """All test functions (with imports header) in included files that mention `name`."""
    chunks = []
    for p in _included_test_files():
        src = p.read_text(encoding="utf-8")
        if name not in src:
            continue
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        lines = src.splitlines(keepends=True)
        header_lines = []
        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                header_lines.append("".join(lines[node.lineno - 1: node.end_lineno]))
        picked = []
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                fn_src = "".join(lines[node.lineno - 1: node.end_lineno])
                if name in fn_src:
                    picked.append(fn_src)
        if picked:
            chunks.append(f"# --- from {p.name} ---\n" + "".join(header_lines) + "\n" + "\n".join(picked))
    return "\n\n".join(chunks) if chunks else "(no existing tests reference this function)"


# ── E2: runtime traces ─────────────────────────────────────────────────────────

_TRACE_PLUGIN = '''
import functools, json, datetime

TRACES = []

def _safe(obj, depth=0):
    if depth > 3:
        return "..."
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    if isinstance(obj, datetime.datetime):
        return f"datetime({obj.isoformat()})"
    if isinstance(obj, dict):
        return {str(k): _safe(v, depth+1) for k, v in list(obj.items())[:12]}
    if isinstance(obj, (list, tuple)):
        return [_safe(x, depth+1) for x in obj[:12]]
    return repr(obj)[:120]

def _wrap(mod, name):
    fn = getattr(mod, name)
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        result = fn(*args, **kwargs)
        try:
            TRACES.append({
                "function": name,
                "args": [_safe(a) for a in args],
                "kwargs": {k: _safe(v) for k, v in kwargs.items()},
                "return": _safe(result),
            })
        except Exception:
            pass
        return result
    setattr(mod, name, wrapper)

def pytest_configure(config):
    from app.ai import stages, conversation_memory, personas
    for name in ("detect_stage", "extract_viewing_datetime"):
        _wrap(stages, name)
    for name in ("detect_landlord_attitude", "landlord_messages",
                 "latest_landlord_asked_for_phone", "outbound_count",
                 "viewing_requested", "phone_shared_state"):
        _wrap(conversation_memory, name)
    for name in ("get_conversation_style", "should_share_phone_now"):
        _wrap(personas, name)

def pytest_unconfigure(config):
    with open(r"{out_path}", "w", encoding="utf-8") as f:
        json.dump(TRACES, f, default=str)
'''


def _capture_traces() -> dict[str, list]:
    out_path = ROOT / "testfix" / "open56_traces_raw.json"
    plugin_path = ROOT / "testfix" / "_open56_trace_plugin.py"
    plugin_path.write_text(
        _TRACE_PLUGIN.replace("{out_path}", str(out_path).replace("\\", "\\\\")),
        encoding="utf-8",
    )
    test_files = [str(p) for p in _included_test_files()]
    try:
        subprocess.run(
            [sys.executable, "-m", "pytest", *test_files,
             "-p", "testfix._open56_trace_plugin", "--tb=no", "-q", "--no-header"],
            capture_output=True, text=True, cwd=ROOT, timeout=300,
        )
    finally:
        plugin_path.unlink(missing_ok=True)

    if not out_path.exists():
        return {}
    traces = json.loads(out_path.read_text(encoding="utf-8"))
    by_func: dict[str, list] = {}
    for t in traces:
        by_func.setdefault(t["function"], []).append(t)
    return by_func


def _format_traces(traces: list, limit: int = 8) -> str:
    if not traces:
        return "(no runtime traces captured for this function)"
    # Dedup identical (args, return) pairs; keep diverse examples
    seen = set()
    picked = []
    for t in traces:
        key = json.dumps({"a": t["args"], "k": t["kwargs"], "r": t["return"]}, sort_keys=True, default=str)
        if key in seen:
            continue
        seen.add(key)
        picked.append(t)
        if len(picked) >= limit:
            break
    out = []
    for t in picked:
        out.append(
            f"call: {t['function']}(args={json.dumps(t['args'], default=str)}, "
            f"kwargs={json.dumps(t['kwargs'], default=str)})\n"
            f"  -> returned: {json.dumps(t['return'], default=str)}"
        )
    return "\n\n".join(out)


# ── E3: comments + docstrings ─────────────────────────────────────────────────

def _extract_comments(entry_func: str, file_rel: str) -> str:
    """Docstring of the function (none exist) + module docstring + # comments
    inside the function body and at module level near it."""
    path = ROOT / file_rel
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    lines = src.splitlines()

    parts = []
    mod_doc = ast.get_docstring(tree)
    parts.append(f"module docstring: {mod_doc!r}")

    fn_node = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == entry_func:
            fn_node = node
            break
    if fn_node is None:
        return "(function not found)"

    parts.append(f"function docstring: {ast.get_docstring(fn_node)!r}")

    comment_lines = [
        f"L{i+1}: {line.strip()}"
        for i, line in enumerate(lines[fn_node.lineno - 1: fn_node.end_lineno], start=fn_node.lineno - 1)
        if line.strip().startswith("#") or "  # " in line
    ]
    parts.append("comments inside function body:\n" + ("\n".join(comment_lines) if comment_lines else "(none)"))
    return "\n".join(parts)


# ── E4: static usage (call sites in app/) ─────────────────────────────────────

def _extract_call_sites(entry_func: str, context: int = 10, limit: int = 6) -> str:
    chunks = []
    for p in sorted((ROOT / "app").rglob("*.py")):
        src = p.read_text(encoding="utf-8")
        if f"{entry_func}(" not in src:
            continue
        lines = src.splitlines()
        for i, line in enumerate(lines):
            if re.search(rf"(?<!def )\b{entry_func}\(", line):
                start = max(0, i - context)
                end = min(len(lines), i + context + 1)
                snippet = "\n".join(lines[start:end])
                rel = p.relative_to(ROOT)
                chunks.append(f"# --- call site in {rel} (line {i+1}) ---\n{snippet}")
                if len(chunks) >= limit:
                    return "\n\n".join(chunks)
    return "\n\n".join(chunks) if chunks else "(no call sites found in app/)"


# ── E-code: original implementation + depth-1 helpers ────────────────────────

def _extract_code(entry_func: str, file_rel: str) -> str:
    from testfix.extractor import _extract_function_source
    from testfix.retriever import retrieve_helpers

    path = ROOT / file_rel
    entry_src = _extract_function_source(path, entry_func)
    if entry_src is None:
        return "(entry function source not found)"
    parts = [f"# === {entry_func} ({file_rel}) ===\n{entry_src}"]
    helpers = retrieve_helpers(path.read_text(encoding="utf-8"))
    # Only helpers actually called by THIS entry function
    called = set(re.findall(r"\b(\w+)\(", entry_src))
    for name, (rel_path, src) in helpers.items():
        if name in called and name != entry_func:
            parts.append(f"# === helper {name} ({rel_path}) ===\n{src}")
    return "\n\n".join(parts)


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print("Capturing runtime traces (running included test files)...")
    traces_by_func = _capture_traces()
    print(f"  traced functions: { {k: len(v) for k, v in traces_by_func.items()} }")

    evidence: dict[str, dict[str, str]] = {}
    for fn, file_rel in ENTRY_FUNCS.items():
        print(f"Building evidence for {fn}...")
        evidence[fn] = {
            "E1": _extract_test_functions_mentioning(fn),
            "E2": _format_traces(traces_by_func.get(fn, [])),
            "E3": _extract_comments(fn, file_rel),
            "E4": _extract_call_sites(fn),
            "E-code": _extract_code(fn, file_rel),
        }

    out = ROOT / "testfix" / "open56_evidence.json"
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(f"\nEvidence written: {out}")
    for fn, ev in evidence.items():
        sizes = {k: len(v) for k, v in ev.items()}
        print(f"  {fn}: {sizes}")


if __name__ == "__main__":
    main()
