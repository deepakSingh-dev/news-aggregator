import logging
import sys

import cartoon
import cluster
import publish
import rank
import summarize

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("main")

STEPS = [
    ("cluster", cluster.main),
    ("summarize", summarize.main),
    ("rank", rank.main),
    ("cartoon", cartoon.main),
    ("publish", publish.main),
]


def main():
    for name, step_fn in STEPS:
        logger.info("=== Starting step: %s ===", name)
        try:
            step_fn()
        except Exception:
            logger.exception("Step '%s' failed -- stopping daily run", name)
            sys.exit(1)
        logger.info("=== Finished step: %s ===", name)

    logger.info("Daily pipeline completed successfully")


if __name__ == "__main__":
    main()
