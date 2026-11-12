"""Run the whole pipeline with one command: python run_pipeline.py [--steps ...].

Steps run in order; each step is idempotent, so re-running is always safe.
The process exits non-zero if any step fails (including failed quality checks).
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from collections.abc import Callable

from src import config, extract, load, quality_checks, run_analysis, transform, warehouse_checks

logger = logging.getLogger("pipeline")

STEPS: dict[str, Callable[[], None]] = {
    "extract": extract.main,
    "transform": transform.main,
    "quality": quality_checks.main,  # stops the pipeline on critical issues
    "load": load.main,
    "verify": warehouse_checks.main,  # read-only post-load checks; stops on failures
    "analysis": run_analysis.main,
}


def main() -> None:
    """Parse CLI arguments and execute the selected steps in order."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--steps", nargs="+", choices=list(STEPS), default=list(STEPS),
                        help="subset of steps to run (default: all)")
    args = parser.parse_args()

    config.setup_logging()
    selected = [name for name in STEPS if name in args.steps]
    logger.info("Pipeline started: steps=%s period=%s..%s", selected, config.START_DATE, config.END_DATE)
    pipeline_start = time.perf_counter()
    for name in selected:
        started = time.perf_counter()
        logger.info("▶ %s", name)
        try:
            STEPS[name]()
        except (Exception, SystemExit) as exc:
            # SystemExit is how quality/verify signal failed checks; log it like any other failure.
            logger.error("✘ %s failed after %.1fs: %s", name, time.perf_counter() - started, exc)
            logger.error("Pipeline aborted; later steps were not run")
            sys.exit(1)
        logger.info("✔ %s (%.1fs)", name, time.perf_counter() - started)
    logger.info("Pipeline finished in %.1fs", time.perf_counter() - pipeline_start)


if __name__ == "__main__":
    main()
