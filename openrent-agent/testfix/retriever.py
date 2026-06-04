"""
testfix.retriever
-----------------
Call-graph retrieval for ARM_B.

Given a function's source, extract all directly called function names (ast.Name
calls only — avoids method chains and module-attribute calls), search app/ for
their top-level definitions, and return {name: (rel_path, source)}.

Run retrieve_helpers() inside a _patched context so that mutated helpers are
read from disk rather than their originals.
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Names to skip — builtins and stdlib functions that will never appear in app/
_SKIP = frozenset([
    "len", "str", "int", "list", "dict", "set", "tuple", "bool", "float",
    "any", "all", "range", "enumerate", "zip", "map", "filter", "sorted",
    "reversed", "print", "repr", "isinstance", "issubclass", "type",
    "getattr", "setattr", "hasattr", "super", "property", "staticmethod",
    "classmethod", "open", "next", "iter", "sum", "min", "max", "abs",
    "round", "format", "vars", "dir", "id", "hash", "ord", "chr",
])


def _extract_called_names(function_source: str) -> set[str]:
    """Return all bare function names called within function_source (ast.Name only)."""
    try:
        tree = ast.parse(function_source)
    except SyntaxError:
        return set()
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            names.add(node.func.id)
    return names - _SKIP


def retrieve_helpers(
    function_source: str,
    app_root: Path | None = None,
) -> dict[str, tuple[str, str]]:
    """
    Find top-level definitions in app/ for all functions called by function_source.

    Returns {func_name: (relative_path_str, source_str)}.
    Reads from disk — call while the target file is patched to capture mutated sources.
    First definition found wins (alphabetical file order within app/).
    """
    if app_root is None:
        app_root = ROOT / "app"

    called = _extract_called_names(function_source)
    if not called:
        return {}

    found: dict[str, tuple[str, str]] = {}
    for py_file in sorted(app_root.rglob("*.py")):
        remaining = called - found.keys()
        if not remaining:
            break
        try:
            src = py_file.read_text(encoding="utf-8")
            tree = ast.parse(src)
        except (OSError, SyntaxError):
            continue
        lines = src.splitlines(keepends=True)
        for node in tree.body:
            if (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name in remaining
            ):
                func_src = "".join(lines[node.lineno - 1 : node.end_lineno])
                rel = str(py_file.relative_to(ROOT)).replace("\\", "/")
                found[node.name] = (rel, func_src)

    return found
