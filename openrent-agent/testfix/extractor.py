"""
testfix.extractor
-----------------
Run a failing pytest test and extract structured context for an AI proposer:
  - the test source (what the fix must satisfy)
  - the target function source (what currently exists)
  - the error message (what went wrong)

Entry point: extract_failure(test_id) -> dict | None
Returns None when the test already passes.
"""

import ast
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def extract_failure(test_id: str) -> dict | None:
    """
    Run test_id and return structured failure context, or None if it passes.

    Returned dict keys:
      test_id, error_type, error_message, pytest_output,
      test_source, target_function, target_file, target_source
    """
    run = _run_pytest(test_id)
    if run["passed"]:
        return None

    output = run["stdout"] + run["stderr"]
    error_type, error_message = _parse_error(output)

    # Try to find the target function.
    # Strategy 1: look for explicit app/ frames in the traceback
    # (fires when the app function raises an exception).
    target_file, target_function = _parse_app_frame(output)

    # Strategy 2: parse the assertion/call line in the test traceback
    # (fires for return-value assertion errors where no app frame is recorded).
    if not target_function:
        target_function = _parse_called_function(output)
        if target_function:
            target_file = _locate_function_in_app(target_function)

    target_source = None
    if target_file and target_function:
        target_source = _extract_function_source(
            ROOT / target_file, target_function
        )

    test_source = _extract_test_source(test_id)

    return {
        "test_id": test_id,
        "error_type": error_type,
        "error_message": error_message,
        "pytest_output": output,
        "test_source": test_source,
        "target_function": target_function,
        "target_file": target_file,
        "target_source": target_source,
    }


# ── pytest runner ─────────────────────────────────────────────────────────────

def _run_pytest(test_id: str) -> dict:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", test_id, "--tb=short", "-q", "--no-header"],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    return {
        "passed": result.returncode == 0,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


# ── output parsing ─────────────────────────────────────────────────────────────

def _parse_error(output: str) -> tuple[str, str]:
    """Extract error type and message from pytest --tb=short output."""
    match = re.search(
        r"^E\s+(\w+(?:Error|Exception|Warning)?):\s*(.+)$",
        output,
        re.MULTILINE,
    )
    if match:
        return match.group(1), match.group(2).strip()
    match = re.search(r"^E\s+(AssertionError)$", output, re.MULTILINE)
    if match:
        return "AssertionError", ""
    return "UnknownError", ""


def _parse_app_frame(output: str) -> tuple[str | None, str | None]:
    """
    Find the last app/ frame in the traceback.
    Matches lines like: app/ai/stages.py:92: in detect_stage
    This fires when the app function raises an exception.
    """
    frames = re.findall(r"(app/[^\s]+\.py)[:\s]+\d+[:\s]+in\s+(\w+)", output)
    if not frames:
        # Windows path separator
        frames = re.findall(r"(app\\[^\s]+\.py)[:\s]+\d+[:\s]+in\s+(\w+)", output)
    if not frames:
        return None, None
    file_path, func_name = frames[-1]
    return file_path.replace("\\", "/"), func_name


def _parse_called_function(output: str) -> str | None:
    """
    Extract the function name from an assertion line in the test traceback.
    Handles: 'assert detect_stage(messages) == ...'
    Falls back to any bare function call in the test code lines.
    """
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith("assert "):
            match = re.search(r"assert\s+(\w+)\s*\(", stripped)
            if match:
                return match.group(1)
    # Fallback: any function call on a non-E line that looks like test body
    for line in output.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("E ") and not stripped.startswith("_"):
            match = re.search(r"\b([a-z]\w+)\s*\(", stripped)
            if match and match.group(1) not in ("assert", "print", "len", "str", "int", "list"):
                return match.group(1)
    return None


# ── app/ function lookup ───────────────────────────────────────────────────────

def _locate_function_in_app(function_name: str) -> str | None:
    """Search app/ recursively for a top-level function definition. Returns relative path."""
    app_dir = ROOT / "app"
    if not app_dir.exists():
        return None
    for py_file in sorted(app_dir.rglob("*.py")):
        try:
            source = py_file.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except (OSError, SyntaxError):
            continue
        for node in tree.body:
            if (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == function_name
            ):
                return str(py_file.relative_to(ROOT)).replace("\\", "/")
    return None


# ── source extraction ──────────────────────────────────────────────────────────

def _extract_function_source(file_path: Path, function_name: str) -> str | None:
    """Extract source of a top-level function from a Python file."""
    try:
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (OSError, SyntaxError):
        return None

    lines = source.splitlines(keepends=True)
    for node in tree.body:
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == function_name
        ):
            return "".join(lines[node.lineno - 1 : node.end_lineno])
    return None


def _extract_test_source(test_id: str) -> str | None:
    """Extract the test function source. test_id: 'tests/foo.py::test_name'"""
    if "::" not in test_id:
        return None
    file_part, func_name = test_id.rsplit("::", 1)
    return _extract_function_source(ROOT / file_part, func_name)
