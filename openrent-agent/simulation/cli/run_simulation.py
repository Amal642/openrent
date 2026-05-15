import argparse
import json

from simulation.engine.runner import run_simulation


def main():
    parser = argparse.ArgumentParser(
        description="Run a deterministic simulation session."
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-turns", type=int, default=1)
    args = parser.parse_args()

    session = run_simulation(
        deterministic_seed=args.seed,
        max_turns=args.max_turns,
    )

    print(json.dumps(session.to_dict(), indent=2))


if __name__ == "__main__":
    main()

