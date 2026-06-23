import sqlite3

DB_FILE = "articles.db"
TOP_N = 20


def ensure_selected_column(conn):
    cols = [row[1] for row in conn.execute("PRAGMA table_info(daily_stories)").fetchall()]
    if "selected" not in cols:
        conn.execute("ALTER TABLE daily_stories ADD COLUMN selected INTEGER DEFAULT 0")
        conn.commit()


def rank_clusters(conn):
    return conn.execute("""
        SELECT c.cluster_id, COUNT(DISTINCT a.source) AS outlet_count
        FROM clusters c
        JOIN articles a ON a.id = c.article_id
        GROUP BY c.cluster_id
        ORDER BY outlet_count DESC
    """).fetchall()


def headline_for_cluster(conn, cluster_id):
    row = conn.execute("""
        SELECT a.title
        FROM clusters c
        JOIN articles a ON a.id = c.article_id
        WHERE c.cluster_id = ?
        ORDER BY a.id
        LIMIT 1
    """, (cluster_id,)).fetchone()
    return row[0] if row else "(no headline found)"


def main():
    conn = sqlite3.connect(DB_FILE)
    ensure_selected_column(conn)

    ranked = rank_clusters(conn)
    top = ranked[:TOP_N]

    conn.execute("UPDATE daily_stories SET selected = 0")
    conn.executemany(
        "UPDATE daily_stories SET selected = 1 WHERE cluster_id = ?",
        [(cluster_id,) for cluster_id, _ in top],
    )
    conn.commit()

    print(f"Top {len(top)} clusters by distinct outlet count:\n")
    for rank, (cluster_id, outlet_count) in enumerate(top, start=1):
        headline = headline_for_cluster(conn, cluster_id)
        print(f"{rank:>2}. [{outlet_count} outlets] {headline}")

    conn.close()


if __name__ == "__main__":
    main()
