import logging
import time
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler

from ingest import run_ingestion

RUN_INTERVAL_MINUTES = 30
RUN_DURATION_SECONDS = 65 * 60  # keep the process alive a bit past the hour mark

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("scheduler")


def scheduled_ingestion():
    logger.info("Ingestion run starting")
    inserted, duplicates, total = run_ingestion()
    logger.info(
        "Ingestion run finished: inserted=%d duplicates=%d total_rows=%d",
        inserted, duplicates, total,
    )


def main():
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        scheduled_ingestion,
        "interval",
        minutes=RUN_INTERVAL_MINUTES,
        next_run_time=datetime.now(),
    )
    scheduler.start()
    logger.info("Scheduler started, running every %d minutes", RUN_INTERVAL_MINUTES)

    try:
        time.sleep(RUN_DURATION_SECONDS)
    finally:
        logger.info("Shutting down scheduler")
        scheduler.shutdown()


if __name__ == "__main__":
    main()
