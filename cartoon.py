import json
import logging
import os
import sqlite3
import time
import urllib.request

DB_FILE = "articles.db"
ENV_FILE = ".env"
ENDPOINT_ID = "black-forest-labs-flux-1-schnell"
RUN_URL = f"https://api.runpod.ai/v2/{ENDPOINT_ID}/run"
STATUS_URL = f"https://api.runpod.ai/v2/{ENDPOINT_ID}/status/{{job_id}}"
IMAGES_DIR = "images"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("cartoon")


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


def fetch_top_stories(conn):
    return conn.execute("""
        SELECT ds.cluster_id, MIN(a.title)
        FROM daily_stories ds
        JOIN clusters c ON c.cluster_id = ds.cluster_id
        JOIN articles a ON a.id = c.article_id
        WHERE ds.selected = 1
        GROUP BY ds.cluster_id
        ORDER BY ds.cluster_id
    """).fetchall()


def build_prompt(headline):
    return (
        f"Editorial cartoon illustration depicting: {headline}. "
        "Simple, colorful, friendly news-illustration style, no text or captions."
    )


def post_json(url, payload, api_key):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def get_json(url, api_key):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {api_key}"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def submit_job(api_key, prompt):
    result = post_json(RUN_URL, {"input": {
        "prompt": prompt,
        "seed": -1,
        "num_inference_steps": 4,
        "guidance": 7,
        "negative_prompt": "text, watermark, caption, words",
        "image_format": "png",
        "width": 1024,
        "height": 1024,
    }}, api_key)
    return result["id"]


def wait_for_result(api_key, job_id, timeout=120, poll_interval=3):
    deadline = time.time() + timeout
    url = STATUS_URL.format(job_id=job_id)
    while time.time() < deadline:
        data = get_json(url, api_key)
        if data["status"] == "COMPLETED":
            return data["output"]["result"]
        if data["status"] == "FAILED":
            raise RuntimeError(f"Job {job_id} failed: {data}")
        time.sleep(poll_interval)
    raise TimeoutError(f"Job {job_id} did not complete within {timeout}s")


def save_image(image_url, cluster_id):
    os.makedirs(IMAGES_DIR, exist_ok=True)
    ext = image_url.rsplit(".", 1)[-1].split("?")[0] or "jpg"
    path = os.path.join(IMAGES_DIR, f"{cluster_id}.{ext}")
    with urllib.request.urlopen(image_url, timeout=30) as resp:
        content = resp.read()
    with open(path, "wb") as f:
        f.write(content)
    return path


def main():
    load_env()
    api_key = os.environ["RUNPOD_API_KEY"]

    conn = sqlite3.connect(DB_FILE)
    stories = fetch_top_stories(conn)
    logger.info("Generating cartoons for %d top stories", len(stories))

    done = 0
    failed = 0
    for cluster_id, headline in stories:
        try:
            prompt = build_prompt(headline)
            job_id = submit_job(api_key, prompt)
            image_url = wait_for_result(api_key, job_id)
            path = save_image(image_url, cluster_id)
            logger.info("Cluster %d -> %s (%s)", cluster_id, path, headline)
            done += 1
        except Exception:
            logger.exception("Cluster %d failed", cluster_id)
            failed += 1

    logger.info("Finished: %d generated, %d failed", done, failed)
    conn.close()


if __name__ == "__main__":
    main()
