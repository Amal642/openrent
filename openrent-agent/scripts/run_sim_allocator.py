"""
Daily SIM allocation runner.

Assigns unallocated SIMs to the highest-scoring South London area and
rebalances any SIMs stuck in exhausted areas.

Usage:
    python scripts/run_sim_allocator.py            # live run
    python scripts/run_sim_allocator.py --dry-run  # preview only, no DB changes
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from app.services.sim_allocator import run_allocation
from app.utils.logger import logger


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Preview without making changes")
    args = parser.parse_args()

    logger.info(f"SIM_ALLOCATOR_START dry_run={args.dry_run}")

    result = run_allocation(dry_run=args.dry_run)

    for entry in result["assigned"]:
        logger.info(
            f"SIM_ALLOCATED account={entry['account']} area={entry['area']} "
            f"score={entry['score']} phone_rate={entry['phone_rate_pct']}% "
            f"new_listings_7d={entry['new_listings_7d']}"
        )

    for entry in result["rebalanced"]:
        logger.info(
            f"SIM_REBALANCED account={entry['account']} "
            f"from={entry['from_areas']} to={entry['to_area']} "
            f"score={entry['score']} phone_rate={entry['phone_rate_pct']}%"
        )

    for entry in result["skipped"]:
        logger.warning(f"SIM_SKIPPED account={entry['account']} reason={entry['reason']}")

    for warning in result["warnings"]:
        logger.warning(f"SIM_ALLOCATOR_WARNING {warning}")

    logger.info(
        f"SIM_ALLOCATOR_DONE assigned={len(result['assigned'])} "
        f"rebalanced={len(result['rebalanced'])} "
        f"skipped={len(result['skipped'])} "
        f"dry_run={args.dry_run}"
    )

    if args.dry_run:
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
