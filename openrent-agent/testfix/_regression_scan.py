"""
Regression scanner: run the test suite against each of the last N commits
and collect any failures that the extractor can handle.

Usage (from openrent-agent/):
    python testfix/_regression_scan.py

Outputs results to testfix/_regression_results.json
"""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # openrent-agent/
REPO_ROOT = ROOT.parent                        # openrent/ (git root)

N_COMMITS = 10


def git(args, cwd=REPO_ROOT):
    result = subprocess.run(
        ["git"] + args,
        capture_output=True, text=True, cwd=cwd,
    )
    return result.stdout.strip(), result.stderr.strip(), result.returncode


def run_pytest(cwd=ROOT):
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "--tb=short", "-q", "--no-header",
         "--ignore=tests/simulation"],
        capture_output=True, text=True, cwd=cwd,
    )
    return result.stdout + result.stderr, result.returncode


def parse_failures(output):
    """Extract failing test IDs from pytest -q output."""
    failures = []
    for line in output.splitlines():
        if line.startswith("FAILED "):
            test_id = line.split("FAILED ", 1)[1].split(" - ")[0].strip()
            failures.append(test_id)
    return failures


def get_commits():
    stdout, _, _ = git(["log", "--oneline", f"-{N_COMMITS}",
                        "--format=%H %s"])
    commits = []
    for line in stdout.splitlines():
        parts = line.split(" ", 1)
        if len(parts) == 2:
            commits.append({"hash": parts[0], "subject": parts[1]})
    return commits


def main():
    commits = get_commits()
    print(f"Scanning {len(commits)} commits...\n")

    # Save current HEAD
    head_stdout, _, _ = git(["rev-parse", "HEAD"])
    original_head = head_stdout.strip()

    # Stash working changes so checkout doesn't fail on modified tracked files.
    # testfix/ is untracked and persists across stash/checkout untouched.
    stash_stdout, _, stash_rc = git(["stash", "push", "-m", "regression-scan-temp"])
    stashed = "No local changes" not in stash_stdout
    if stashed:
        print(f"Stashed working changes: {stash_stdout}")

    results = []

    try:
        for i, commit in enumerate(commits):
            h = commit["hash"]
            subject = commit["subject"]
            print(f"[{i+1}/{len(commits)}] {h[:8]} — {subject}")

            _, err, rc = git(["checkout", h])
            if rc != 0:
                print(f"  checkout failed: {err}")
                continue

            output, returncode = run_pytest()
            failures = parse_failures(output)

            status = "PASS" if returncode == 0 else f"FAIL ({len(failures)} failures)"
            print(f"  {status}")
            if failures:
                for f in failures:
                    print(f"    - {f}")

            results.append({
                "hash": h,
                "subject": subject,
                "returncode": returncode,
                "failures": failures,
                "output": output,
            })
    finally:
        # Always restore HEAD and working changes
        print(f"\nRestoring HEAD ({original_head[:8]})...")
        git(["checkout", original_head])
        if stashed:
            _, err, rc = git(["stash", "pop"])
            if rc != 0:
                print(f"WARNING: stash pop failed: {err}")
            else:
                print("Working changes restored.")

    out_path = ROOT / "testfix" / "_regression_results.json"
    out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nResults written to {out_path}")

    # Summary
    failing_commits = [r for r in results if r["failures"]]
    print(f"\n{len(failing_commits)} commits with failures out of {len(results)} scanned")
    for r in failing_commits:
        print(f"  {r['hash'][:8]} {r['subject']}: {r['failures']}")


if __name__ == "__main__":
    main()
