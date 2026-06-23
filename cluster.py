import sqlite3
from datetime import date

import numpy as np
from dateutil import parser as dateparser
from sentence_transformers import SentenceTransformer

DB_FILE = "articles.db"
MODEL_NAME = "all-MiniLM-L6-v2"
THRESHOLD = 0.75


def load_todays_articles(conn):
    rows = conn.execute("SELECT id, title, description, published_at FROM articles").fetchall()
    today = date.today()
    articles = []
    for article_id, title, description, published_at in rows:
        try:
            parsed = dateparser.parse(published_at)
        except (ValueError, TypeError, OverflowError):
            continue
        if parsed is None or parsed.date() != today:
            continue
        articles.append((article_id, title or "", description or ""))
    return articles


class UnionFind:
    def __init__(self, n):
        self.parent = list(range(n))

    def find(self, x):
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


def cluster_articles(articles, threshold):
    texts = [f"{title}. {description}" for _, title, description in articles]
    model = SentenceTransformer(MODEL_NAME)
    embeddings = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)

    sims = embeddings @ embeddings.T
    n = len(articles)
    uf = UnionFind(n)

    iu, ju = np.triu_indices(n, k=1)
    pair_sims = sims[iu, ju]
    above = pair_sims >= threshold
    for i, j in zip(iu[above], ju[above]):
        uf.union(int(i), int(j))

    groups = {}
    for idx in range(n):
        root = uf.find(idx)
        groups.setdefault(root, []).append(idx)

    return list(groups.values())


def print_clusters(clusters, articles):
    multi = sorted((c for c in clusters if len(c) > 1), key=len, reverse=True)
    singles = [c for c in clusters if len(c) == 1]

    for cluster_num, idxs in enumerate(multi, start=1):
        print(f"--- Cluster {cluster_num} ({len(idxs)} articles) ---")
        for idx in idxs:
            print(f"  {articles[idx][1]}")
        print()

    print(f"({len(singles)} singleton clusters not shown)")


def save_clusters(conn, clusters, articles):
    conn.execute("DROP TABLE IF EXISTS clusters")
    conn.execute("""
        CREATE TABLE clusters (
            cluster_id INTEGER,
            article_id INTEGER
        )
    """)
    # cluster_id is reassigned from scratch every run, so any daily_stories row from a
    # previous run (including its wp_post_id) no longer corresponds to the same story --
    # keeping it around risks a future run silently overwriting an unrelated live WP post
    # that happens to land on the same cluster_id number.
    conn.execute("DROP TABLE IF EXISTS daily_stories")
    conn.commit()
    rows = [
        (cluster_id, articles[idx][0])
        for cluster_id, idxs in enumerate(clusters)
        for idx in idxs
    ]
    conn.executemany("INSERT INTO clusters (cluster_id, article_id) VALUES (?, ?)", rows)
    conn.commit()


def main():
    conn = sqlite3.connect(DB_FILE)
    articles = load_todays_articles(conn)
    print(f"Loaded {len(articles)} articles from today\n")

    clusters = cluster_articles(articles, THRESHOLD)
    print(f"Formed {len(clusters)} clusters at threshold={THRESHOLD}\n")
    print_clusters(clusters, articles)

    save_clusters(conn, clusters, articles)
    conn.close()


if __name__ == "__main__":
    main()
