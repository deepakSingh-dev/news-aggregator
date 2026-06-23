import logging
import sqlite3

import feedparser

FEEDS_FILE = "feeds.txt"
DB_FILE = "articles.db"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ingest")


def load_feed_urls(path):
    with open(path) as f:
        return [line.strip() for line in f if line.strip()]


def init_db(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            link TEXT UNIQUE,
            source TEXT,
            published_at TEXT,
            description TEXT
        )
    """)
    conn.commit()


def ingest_feed(conn, url):
    feed = feedparser.parse(url)
    source = feed.feed.get("title", url)

    inserted = 0
    duplicates = 0
    for entry in feed.entries:
        title = entry.get("title", "")
        link = entry.get("link", "")
        published = entry.get("published", entry.get("updated", ""))
        description = entry.get("summary", "")

        try:
            conn.execute(
                "INSERT INTO articles (title, link, source, published_at, description) "
                "VALUES (?, ?, ?, ?, ?)",
                (title, link, source, published, description),
            )
            inserted += 1
        except sqlite3.IntegrityError:
            duplicates += 1

    return inserted, duplicates


def run_ingestion():
    conn = sqlite3.connect(DB_FILE)
    init_db(conn)

    total_inserted = 0
    total_duplicates = 0
    failed = 0

    for url in load_feed_urls(FEEDS_FILE):
        try:
            inserted, duplicates = ingest_feed(conn, url)
            conn.commit()
            total_inserted += inserted
            total_duplicates += duplicates
        except Exception:
            logger.exception("Feed failed, skipping: %s", url)
            failed += 1

    total = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
    conn.close()

    return total_inserted, total_duplicates, total, failed


def main():
    inserted, duplicates, total, failed = run_ingestion()
    logger.info(
        "Inserted: %d  Duplicates skipped: %d  Feeds failed: %d  Total rows in db: %d",
        inserted, duplicates, failed, total,
    )


if __name__ == "__main__":
    main()
