import sqlite3

import feedparser

FEEDS_FILE = "feeds.txt"
DB_FILE = "articles.db"


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


def main():
    conn = sqlite3.connect(DB_FILE)
    init_db(conn)

    inserted = 0
    duplicates = 0

    for url in load_feed_urls(FEEDS_FILE):
        feed = feedparser.parse(url)
        source = feed.feed.get("title", url)

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

    conn.commit()

    total = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
    print(f"Inserted: {inserted}  Duplicates skipped: {duplicates}  Total rows in db: {total}")

    conn.close()


if __name__ == "__main__":
    main()
