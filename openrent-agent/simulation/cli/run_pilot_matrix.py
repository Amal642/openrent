"""CLI for the N\u00d7K pilot matrix.

Default invocation (a0 baseline \u2014 memory off, deterministic, 100 trials):

    python -m simulation.cli.run_pilot_matrix \\
        --fixture simulation/pilot/scenarios.k10.json \\
        --n-trials 10 \\
        --seed-base 1000 \\
        --memory off \\
        --output-dir pilot_matrix_results/a0

a1 (memory-on, shared snap across all trials):

    python -m simulation.cli.run_pilot_matrix \\
        --memory on \\
        --memory-regime shared \\
        --hippo-server-js D:/hippocampus-prodV1/packages/memory-kit-mcp/dist/stdio.js \\
        --output-dir pilot_matrix_results/a1

Both conditions in one shot (good for paired difference analysis):

    python -m simulation.cli.run_pilot_matrix --memory both
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from simulation.pilot.fixtures import load_pilot_fixture
from simulation.pilot.matrix import MatrixConfig, run_pilot_matrix


_DEFAULT_FIXTURE = Path(__file__).resolve().parents[1] / "pilot" / "scenarios.k10.json"


def _memory_arg(value: str) -> tuple[str, ...]:
    normalized = (value or "").strip().lower()
    mapping = {
        "off": ("memory-off",),
        "on": ("memory-on",),
        "both": ("memory-off", "memory-on"),
    }
    if normalized not in mapping:
        raise argparse.ArgumentTypeError(
            f"expected 'off' / 'on' / 'both' (got {value!r})"
        )
    return mapping[normalized]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_pilot_matrix",
        description="Run an N\u00d7K pilot-matrix sweep with optional memory toggle.",
    )
    parser.add_argument(
        "--fixture",
        type=Path,
        default=_DEFAULT_FIXTURE,
        help="Path to the K-scenario fixture JSON (default: scenarios.k10.json).",
    )
    parser.add_argument(
        "--n-trials",
        type=int,
        default=10,
        help="N seeds per (condition, scenario) cell (default: 10).",
    )
    parser.add_argument(
        "--seed-base",
        type=int,
        default=1000,
        help="First deterministic seed; trial seeds = seed_base + i (default: 1000).",
    )
    parser.add_argument(
        "--memory",
        type=_memory_arg,
        default=_memory_arg("off"),
        metavar="off|on|both",
        help="Which conditions to run (default: off).",
    )
    parser.add_argument(
        "--memory-regime",
        choices=["shared", "per-trial"],
        default="shared",
        help=(
            "shared = one MCP client across all trials (default); "
            "per-trial = fresh snap per trial."
        ),
    )
    parser.add_argument(
        "--hippo-server-js",
        type=str,
        default=None,
        help="Path to memory-kit-mcp stdio.js (or set HIPPO_STDIO_JS env var).",
    )
    parser.add_argument(
        "--hippo-snap",
        type=str,
        default=":memory:",
        help="Storage path for the shared snap (default ':memory:', no persistence).",
    )
    parser.add_argument(
        "--hippo-project-id",
        type=str,
        default="openrent-sim-pilot",
        help="Project id prefix for hippo cells (default: openrent-sim-pilot).",
    )
    parser.add_argument(
        "--hippo-thread-prefix",
        type=str,
        default="",
        help=(
            "Optional prefix prepended to each scenario's thread_id; useful "
            "to avoid colliding with prior pilot runs in the same snap."
        ),
    )
    parser.add_argument(
        "--hippo-k-evidence",
        type=int,
        default=8,
        help=(
            "Number of evidence cells requested per Hippo recall "
            "(default: 8). Lower values are useful for prompt-budget probes."
        ),
    )
    parser.add_argument(
        "--trace-samples",
        action="store_true",
        help=(
            "Write trace_samples.jsonl with compact recall/reply diagnostics "
            "beside the standard matrix artifacts."
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help=(
            "Write trials.jsonl + per_scenario.json + manifest.json into "
            "this directory. When omitted, results are only printed to stdout."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    fixture = load_pilot_fixture(args.fixture)
    config = MatrixConfig(
        fixture=fixture,
        n_trials=args.n_trials,
        seed_base=args.seed_base,
        memory=tuple(args.memory),
        memory_regime=args.memory_regime,
        output_dir=args.output_dir,
        hippo_server_js=args.hippo_server_js,
        hippo_snap=args.hippo_snap,
        hippo_project_id=args.hippo_project_id,
        hippo_thread_prefix=args.hippo_thread_prefix,
        hippo_k_evidence=args.hippo_k_evidence,
        trace_samples=args.trace_samples,
    )
    result = run_pilot_matrix(config)
    summary = {
        "manifest": result.manifest,
        "aggregates": result.aggregates,
    }
    print(json.dumps(summary, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
