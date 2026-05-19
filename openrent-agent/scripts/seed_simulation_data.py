import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from simulation.scenarios.generators import get_default_scenario


def main():
    scenario = get_default_scenario()
    print(f"Loaded simulation scenario: {scenario.scenario_id}")


if __name__ == "__main__":
    main()
