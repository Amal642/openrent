"""
testfix.verifier
----------------
Apply a proposed function replacement and run a specific test.

Entry point: verify_fix(test_id, proposed_source, target_file, function_name) -> dict

The original file is always restored, even on crash.
"""

import ast
import contextlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def verify_fix(
    test_id: str,
    proposed_source: str,
    target_file: str,
    function_name: str,
) -> dict:
    """
    Replace function_name in target_file with proposed_source, run test_id,
    restore the original regardless of outcome.

    Returns:
      passed (bool), error (str | None), pytest_output (str)
    """
    target_path = ROOT / target_file

    try:
        original_source = target_path.read_text(encoding="utf-8")
    except OSError as exc:
        return {"passed": False, "error": f"Cannot read {target_file}: {exc}", "pytest_output": ""}

    patched = _replace_function(original_source, function_name, proposed_source)
    if patched is None:
        return {
            "passed": False,
            "error": f"Function '{function_name}' not found in {target_file}",
            "pytest_output": "",
        }

    try:
        ast.parse(patched)
    except SyntaxError as exc:
        return {
            "passed": False,
            "error": f"Proposed fix has a syntax error: {exc}",
            "pytest_output": "",
        }

    with _patched(target_path, patched, original_source):
        result = subprocess.run(
            [sys.executable, "-m", "pytest", test_id, "--tb=short", "-q", "--no-header"],
            capture_output=True,
            text=True,
            cwd=ROOT,
        )

    return {
        "passed": result.returncode == 0,
        "error": None,
        "pytest_output": result.stdout + result.stderr,
    }


def _clear_pyc(py_path: Path) -> None:
    """Delete compiled bytecode so the next subprocess compiles fresh from the written file."""
    cache_dir = py_path.parent / "__pycache__"
    for pyc in cache_dir.glob(f"{py_path.stem}.*.pyc"):
        try:
            pyc.unlink()
        except OSError:
            pass


@contextlib.contextmanager
def _patched(path: Path, new_source: str, original_source: str):
    """Write new_source to path, yield, then restore original_source."""
    path.write_text(new_source, encoding="utf-8")
    _clear_pyc(path)
    try:
        yield
    finally:
        path.write_text(original_source, encoding="utf-8")
        _clear_pyc(path)


def _replace_function(source: str, function_name: str, new_source: str) -> str | None:
    """
    Replace the named top-level function in source with new_source.
    Returns the modified source, or None if the function is not found.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    lines = source.splitlines(keepends=True)
    for node in tree.body:
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == function_name
        ):
            start = node.lineno - 1
            end = node.end_lineno
            replacement = new_source.rstrip("\n") + "\n"
            return "".join(lines[:start]) + replacement + "".join(lines[end:])

    return None
