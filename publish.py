import base64
import json
import logging
import mimetypes
import os
import sqlite3
import urllib.error
import urllib.request

from anthropic import Anthropic

DB_FILE = "articles.db"
ENV_FILE = ".env"
IMAGES_DIR = "images"
WP_BASE_URL = "https://heraldtimes.org/wp-json/wp/v2"
HAIKU_MODEL = "claude-haiku-4-5-20251001"

ALLOWED_CATEGORY_SLUGS = {
    "business-economy", "entertainment-culture", "health-environment",
    "politics-society", "sports", "technology-science", "world", "uncategorized",
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("publish")


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


def auth_header():
    token = base64.b64encode(
        f"{os.environ['WP_USER']}:{os.environ['WP_APP_PASSWORD']}".encode()
    ).decode()
    return {"Authorization": f"Basic {token}"}


def wp_request(path, data=None, headers=None, method="GET"):
    req = urllib.request.Request(
        f"{WP_BASE_URL}{path}",
        data=data,
        headers={**auth_header(), **(headers or {})},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        raise RuntimeError(f"WP API {method} {path} failed: HTTP {e.code}: {body}") from None


def fetch_categories():
    cats = wp_request("/categories?per_page=100")
    return {c["slug"]: c["id"] for c in cats if c["slug"] in ALLOWED_CATEGORY_SLUGS}


def pick_category(client, categories, title, summary):
    slugs = sorted(categories)
    prompt = (
        f"Story headline: {title}\nStory summary: {summary}\n\n"
        f"Pick the single best matching category from this list: {', '.join(slugs)}\n"
        "Respond with ONLY the category slug, nothing else."
    )
    response = client.messages.create(
        model=HAIKU_MODEL,
        max_tokens=20,
        messages=[{"role": "user", "content": prompt}],
    )
    slug = response.content[0].text.strip().lower()
    if slug not in categories:
        logger.warning("Unrecognized category slug %r, falling back to uncategorized", slug)
        slug = "uncategorized"
    return categories[slug]


def find_image_path(cluster_id):
    for ext in ("jpeg", "jpg", "png"):
        path = os.path.join(IMAGES_DIR, f"{cluster_id}.{ext}")
        if os.path.exists(path):
            return path
    raise FileNotFoundError(f"No image found for cluster {cluster_id}")


def upload_media(image_path):
    filename = os.path.basename(image_path)
    mime_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    with open(image_path, "rb") as f:
        data = f.read()
    result = wp_request(
        "/media",
        data=data,
        headers={
            "Content-Type": mime_type,
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
        method="POST",
    )
    return result["id"]


SOURCES_SHOWN = 2


def build_content_html(summary, links):
    paragraphs = [p.strip() for p in summary.split("\n\n") if p.strip()]
    summary_html = "\n".join(f"<p>{p}</p>" for p in paragraphs)
    items = "".join(f"<li><a href=\"{link}\">{link}</a></li>" for link in links[:SOURCES_SHOWN])
    return f"{summary_html}\n<p><strong>Sources:</strong></p>\n<ul>{items}</ul>"


def create_post(title, content, category_id, media_id, status, existing_post_id=None):
    payload = {
        "title": title,
        "content": content,
        "status": status,
        "categories": [category_id],
        "featured_media": media_id,
    }
    path = f"/posts/{existing_post_id}" if existing_post_id else "/posts"
    return wp_request(
        path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )


def ensure_wp_columns(conn):
    cols = [row[1] for row in conn.execute("PRAGMA table_info(daily_stories)").fetchall()]
    if "wp_post_id" not in cols:
        conn.execute("ALTER TABLE daily_stories ADD COLUMN wp_post_id INTEGER")
    if "wp_link" not in cols:
        conn.execute("ALTER TABLE daily_stories ADD COLUMN wp_link TEXT")
    conn.commit()


def fetch_story(conn, cluster_id):
    summary, links_json = conn.execute(
        "SELECT summary, links FROM daily_stories WHERE cluster_id=?", (cluster_id,)
    ).fetchone()
    title = conn.execute(
        "SELECT MIN(a.title) FROM clusters c JOIN articles a ON a.id = c.article_id "
        "WHERE c.cluster_id=?",
        (cluster_id,),
    ).fetchone()[0]
    return title, summary, json.loads(links_json)


def publish_story(conn, client, categories, cluster_id, status="publish"):
    title, summary, links = fetch_story(conn, cluster_id)
    image_path = find_image_path(cluster_id)

    existing_post_id = conn.execute(
        "SELECT wp_post_id FROM daily_stories WHERE cluster_id=?", (cluster_id,)
    ).fetchone()[0]

    media_id = upload_media(image_path)
    logger.info("Cluster %d: uploaded media id %d", cluster_id, media_id)

    category_id = pick_category(client, categories, title, summary)
    content = build_content_html(summary, links)
    post = create_post(title, content, category_id, media_id, status, existing_post_id)

    conn.execute(
        "UPDATE daily_stories SET wp_post_id=?, wp_link=? WHERE cluster_id=?",
        (post["id"], post.get("link"), cluster_id),
    )
    conn.commit()

    action = "updated" if existing_post_id else "published"
    logger.info("Cluster %d: %s post id %d -> %s", cluster_id, action, post["id"], post.get("link"))
    return post


def main():
    load_env()
    client = Anthropic()

    conn = sqlite3.connect(DB_FILE)
    ensure_wp_columns(conn)
    categories = fetch_categories()

    top_ids = [row[0] for row in conn.execute(
        "SELECT cluster_id FROM daily_stories WHERE selected=1 ORDER BY cluster_id"
    )]
    logger.info("Publishing %d top stories", len(top_ids))

    done = 0
    failed = 0
    for cluster_id in top_ids:
        try:
            publish_story(conn, client, categories, cluster_id, status="publish")
            done += 1
        except Exception:
            logger.exception("Cluster %d failed to publish", cluster_id)
            failed += 1

    logger.info("Finished: %d published/updated, %d failed", done, failed)
    conn.close()


if __name__ == "__main__":
    main()
