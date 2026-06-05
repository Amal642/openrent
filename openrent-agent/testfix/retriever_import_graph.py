"""
testfix.retriever_import_graph
------------------------------
Module-import-graph retrieval for ARM_B4 and ARM_B5.

Given function A's file, retrieve all top-level functions from:
  1. A's own module
  2. Every module that A's module imports from (1 level deep, within app/ only)

This is structurally distinct from ARM_B (direct call-graph from A's body):
  - ARM_B: walks A's AST, collects bare call names, searches for definitions
  - ARM_B4: walks A's module-level imports, collects ALL functions from imported modules

The import graph captures helpers that A never calls directly but that
module-mates of A do call (e.g. _sender, _content in conversation_memory.py,
which are called by landlord_messages/viewing_requested, not by A itself).

Returns {func_name: (rel_path, source)}.
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _resolve_import_path(module_str: str, app_root: Path) -> Path | None:
    """
    Convert a dotted module name like 'app.ai.personas' to an absolute file path.
    Returns None if the module is not inside app_root or can't be resolved.
    """
    # Only resolve app.* imports (stay within the project)
    if not module_str.startswith("app"):
        return None
    rel = module_str.replace(".", "/") + ".py"
    candidate = ROOT / rel
    if candidate.exists():
        return candidate
    # Try as a package __init__
    candidate2 = ROOT / rel.replace(".py", "/__init__.py")
    if candidate2.exists():
        return candidate2
    return None


def _parse_imported_modules(file_path: Path) -> list[Path]:
    """
    Parse all `import X` and `from X import Y` statements in file_path.
    Return resolved Path objects for modules that live inside app/.
    Only 1 level: we parse A's file's imports, not their imports.
    """
    try:
        src = file_path.read_text(encoding="utf-8")
        tree = ast.parse(src)
    except (OSError, SyntaxError):
        return []

    app_root = ROOT / "app"
    imported: list[Path] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                p = _resolve_import_path(alias.name, app_root)
                if p and p != file_path and p not in imported:
                    imported.append(p)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                p = _resolve_import_path(node.module, app_root)
                if p and p != file_path and p not in imported:
                    imported.append(p)
    return imported


def _collect_functions(py_file: Path) -> dict[str, tuple[str, str]]:
    """
    Return {func_name: (rel_path, source)} for all top-level functions in py_file.
    """
    try:
        src = py_file.read_text(encoding="utf-8")
        tree = ast.parse(src)
    except (OSError, SyntaxError):
        return {}
    lines = src.splitlines(keepends=True)
    rel = str(py_file.relative_to(ROOT)).replace("\\", "/")
    result: dict[str, tuple[str, str]] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            func_src = "".join(lines[node.lineno - 1: node.end_lineno])
            result[node.name] = (rel, func_src)
    return result


def retrieve_module_context(
    entry_file: str,
    app_root: Path | None = None,
    exclude_function: str | None = None,
) -> dict[str, tuple[str, str]]:
    """
    Return all top-level functions reachable within 1 import hop from entry_file.

    Includes:
      - All top-level functions in entry_file itself
      - All top-level functions in every module that entry_file imports from
        (only modules inside app/)

    Returns {func_name: (rel_path, source)}.
    exclude_function: skip this name from results (typically function A).
    First definition wins on name collision across files.
    """
    if app_root is None:
        app_root = ROOT / "app"

    entry_path = ROOT / entry_file
    if not entry_path.exists():
        return {}

    # Collect A's own module functions first
    result = _collect_functions(entry_path)

    # Then collect from each imported module (1 hop)
    for imported_path in _parse_imported_modules(entry_path):
        for name, (rel, src) in _collect_functions(imported_path).items():
            if name not in result:  # first definition wins
                result[name] = (rel, src)

    # Filter out entry-point function A
    if exclude_function and exclude_function in result:
        del result[exclude_function]

    return result
