"""Run the whole pipeline with one command: python run_pipeline.py [--steps ...].

Steps run in order; each step is idempotent, so re-running is always safe.
"""

from __future__ import annotations

import argparse
import logging
import time
from collections.abc import Callable

from src import config, extract, load, quality_checks, run_analysis, transform

logger = logging.getLogger("pipeline")

STEPS: dict[str, Callable[[], None]] = {
    "extract": extract.main,
    "transform": transform.main,
    "quality": quality_checks.main,  # stops the pipeline on critical issues
    "load": load.main,
    "analysis": run_analysis.main,
}


def main() -> None:
    """Parse CLI arguments and execute the selected steps in order."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--steps", nargs="+", choices=list(STEPS), default=list(STEPS),
                        help="subset of steps to run (default: all)")
    args = parser.parse_args()

    config.setup_logging()
    for name in STEPS:
        if name not in args.steps:
            continue
        started = time.perf_counter()
        logger.info("▶ %s", name)
        STEPS[name]()
        logger.info("✔ %s (%.1fs)", name, time.perf_counter() - started)


if __name__ == "__main__":
    main()
