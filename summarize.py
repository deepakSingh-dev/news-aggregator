import json
import logging
import os
import sqlite3

from anthropic import Anthropic

DB_FILE = "articles.db"
ENV_FILE = ".env"
MODEL = "claude-haiku-4-5-20251001"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("summarize")


def load_env(path=ENV_FILE):
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ[key.strip()] = value.strip()


def fetch_clusters(conn):
    rows = conn.execute("""
        SELECT c.cluster_id, a.title, a.link, a.description
        FROM clusters c
        JOIN articles a ON a.id = c.article_id
        ORDER BY c.cluster_id
    """).fetchall()

    clusters = {}
    for cluster_id, title, link, description in rows:
        clusters.setdefault(cluster_id, []).append(
            {"title": title, "link": link, "description": description}
        )
    return clusters


def init_daily_stories(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS daily_stories (
            cluster_id INTEGER PRIMARY KEY,
            summary TEXT,
            links TEXT
        )
    """)
    conn.commit()


def build_prompt(articles):
    articles_block = "\n".join(
        f"{i}. Title: {a['title']}\n   Link: {a['link']}\n   Description: {a['description']}"
        for i, a in enumerate(articles, start=1)
    )

    return f"""Here are {len(articles)} news article(s) covering the same story:

{articles_block}

Write a neutral summary based only on the information above -- do not add facts \
that aren't in the articles. Include relevant background and context on why this \
story matters, not just a bare recap of the headline. Format it as 4-5 short \
paragraphs (1-2 sentences each), separated by a blank line, like a typical news \
article -- not one big block of text. Then list the source links exactly as \
given above, with no changes.

Respond with ONLY valid JSON, no other text, in this exact shape (use \\n\\n \
inside the summary string to separate paragraphs):
{{"summary": "paragraph one.\\n\\nparagraph two.\\n\\n...", "links": ["...", "..."]}}"""


def parse_response(text):
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    return json.loads(text)


def summarize_cluster(client, cluster_id, articles):
    prompt = build_prompt(articles)
    max_tokens = min(4096, 900 + 80 * len(articles))
    response = client.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    data = parse_response(response.content[0].text)

    real_links = {a["link"] for a in articles}
    returned_links = set(data.get("links", []))
    hallucinated = returned_links - real_links
    if hallucinated:
        logger.warning("Cluster %d: model returned links not in source set: %s", cluster_id, hallucinated)

    return data["summary"], data.get("links", [])


def save_story(conn, cluster_id, summary, links):
    conn.execute(
        """
        INSERT INTO daily_stories (cluster_id, summary, links) VALUES (?, ?, ?)
        ON CONFLICT(cluster_id) DO UPDATE SET summary=excluded.summary, links=excluded.links
        """,
        (cluster_id, summary, json.dumps(links)),
    )


def main():
    load_env()
    client = Anthropic()

    conn = sqlite3.connect(DB_FILE)
    init_daily_stories(conn)
    clusters = fetch_clusters(conn)
    logger.info("Summarizing %d clusters", len(clusters))

    done = 0
    failed = 0
    for cluster_id, articles in clusters.items():
        try:
            summary, links = summarize_cluster(client, cluster_id, articles)
            save_story(conn, cluster_id, summary, links)
            conn.commit()
            done += 1
        except Exception:
            logger.exception("Cluster %d failed", cluster_id)
            failed += 1

        if done % 25 == 0 and done:
            logger.info("Progress: %d/%d done", done, len(clusters))

    logger.info("Finished: %d summarized, %d failed", done, failed)
    conn.close()


if __name__ == "__main__":
    main()
