import argparse
import json

from simulation.engine.runner import run_simulation


def _on_off(value: str) -> bool:
    normalized = (value or "").strip().lower()
    if normalized in {"on", "true", "1", "yes"}:
        return True
    if normalized in {"off", "false", "0", "no", ""}:
        return False
    raise argparse.ArgumentTypeError(
        f"expected 'on' or 'off' (got {value!r})"
    )


def main():
    parser = argparse.ArgumentParser(
        description="Run a deterministic simulation session."
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-turns", type=int, default=1)
    parser.add_argument(
        "--hippo-memory",
        type=_on_off,
        default=False,
        metavar="on|off",
        help=(
            "Enable hippocampus memory recall + ingest hooks via the "
            "memory-kit MCP bridge (default: off, no MCP traffic)."
        ),
    )
    parser.add_argument(
        "--hippo-snap",
        type=str,
        default=None,
        help=(
            "Storage path for the hippocampus snap. Defaults to "
            "':memory:' (no persistence). Used only when "
            "--hippo-memory on."
        ),
    )
    parser.add_argument(
        "--hippo-server-js",
        type=str,
        default=None,
        help=(
            "Path to memory-kit-mcp stdio.js entrypoint. Falls back to "
            "the HIPPO_STDIO_JS environment variable when omitted."
        ),
    )
    parser.add_argument(
        "--hippo-project-id",
        type=str,
        default="openrent-sim",
        help="Project namespace for hippocampus cells (default: openrent-sim).",
    )
    parser.add_argument(
        "--hippo-thread-id",
        type=str,
        default=None,
        help=(
            "Stable thread id for cross-session memory. Defaults to "
            "the per-run uuid (no cross-session reuse)."
        ),
    )
    args = parser.parse_args()

    session = run_simulation(
        deterministic_seed=args.seed,
        max_turns=args.max_turns,
        hippo_memory=args.hippo_memory,
        hippo_snap=args.hippo_snap,
        hippo_server_js=args.hippo_server_js,
        hippo_project_id=args.hippo_project_id,
        hippo_thread_id=args.hippo_thread_id,
    )

    print(json.dumps(session.to_dict(), indent=2))


if __name__ == "__main__":
    main()
