import feedparser

FEEDS_FILE = "feeds.txt"


def load_feed_urls(path):
    with open(path) as f:
        return [line.strip() for line in f if line.strip()]


def main():
    for url in load_feed_urls(FEEDS_FILE):
        feed = feedparser.parse(url)
        source = feed.feed.get("title", url)

        for entry in feed.entries:
            title = entry.get("title", "")
            link = entry.get("link", "")
            published = entry.get("published", entry.get("updated", ""))
            description = entry.get("summary", "")

            print(f"[{source}] {title}")
            print(f"  link: {link}")
            print(f"  published: {published}")
            print(f"  description: {description[:200]}")
            print()


if __name__ == "__main__":
    main()
