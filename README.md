# news-aggregator

Pulls news from ~30 RSS feeds, groups articles covering the same story, writes a
neutral AI summary of each, generates a cartoon image for the day's biggest
stories, and publishes them to heraldtimes.org. Runs once a day, unattended.

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# then fill in .env:
#   ANTHROPIC_API_KEY  - console.anthropic.com
#   RUNPOD_API_KEY     - runpod.io account settings (needs Read & Write scope)
#   WP_USER            - your WordPress login username
#   WP_APP_PASSWORD    - generate in wp-admin -> Users -> Profile -> Application Passwords
#                        (NOT your regular login password)
```

## Run

```bash
python main.py
```

That's the whole pipeline: gather news -> cluster -> summarize -> rank -> generate
images -> publish. A cron entry runs this once a day:

```
0 6 * * * cd /path/to/news-aggregator && ./venv/bin/python main.py >> main_run.log 2>&1
```

If a step fails outright, `main.py` logs the full error and stops rather than
running later steps on missing data. If a single story fails inside a step
(one bad API response, one missing image), that step logs it and keeps going
on the rest -- one bad story doesn't take down the whole day's run.

## Files

| File | Purpose |
|---|---|
| `feeds.txt` | One RSS feed URL per line -- the input list. |
| `ingest.py` | Fetches every feed, stores new articles in `articles.db` (`articles` table). |
| `cluster.py` | Groups today's articles into same-story clusters (`clusters` table). |
| `summarize.py` | Claude Haiku writes a neutral summary + source links per cluster (`daily_stories` table). |
| `rank.py` | Picks the top 20 clusters by distinct outlet count, marks them `selected`. |
| `cartoon.py` | Generates a cartoon image per selected story via RunPod (`images/<cluster_id>.jpeg`). |
| `publish.py` | Uploads each image and publishes/updates the WordPress post. |
| `main.py` | Runs all of the above in order; the only thing the cron job calls. |
| `articles.db` | SQLite database (gitignored) -- all pipeline state lives here. |

## Why it's built this way

**SQLite, not a real database server.** This is a single-machine batch job
processing a few thousand rows a day -- a whole database server would be pure
overhead. One file, no setup, trivially inspectable with `sqlite3 articles.db`.

**Embeddings, not keyword matching, for clustering.** Different outlets never
use the same words for the same story ("Starmer quits" vs "UK PM resigns").
Keyword/regex matching can't catch that; sentence embeddings (a small local
model, `all-MiniLM-L6-v2`) capture meaning instead. The similarity threshold
(0.75) was tuned by actually comparing output at 0.65/0.75/0.85 against real
headlines, not picked arbitrarily -- 0.65 merged unrelated stories together,
0.85 split obvious duplicates apart.

**Haiku, not a bigger model, for summarization.** This step makes one LLM call
per cluster -- hundreds per day. Haiku is the cheapest Claude model and is
plenty capable for "summarize these short news blurbs neutrally." Calls are
synchronous, one at a time, not via the Anthropic Batch API -- fine at this
volume, but batching would be the first thing to change if cluster counts grew
much larger.

**Outlet count, not an ML model, for ranking.** How many distinct sources are
covering a story is already a strong, simple, fully-explainable proxy for "how
big is this story" -- no need for anything fancier.

**RunPod serverless, not a persistent GPU pod.** The original plan was a
ComfyUI pod, but the RunPod API key turned out to be read-only at the pod-
deploy level. Serverless Flux-Schnell needed no extra permissions, costs
~$0.003/image instead of hourly GPU billing, and is simpler to call (one HTTP
request) for a low-volume job like 20 images/day.

**WordPress REST API + Application Passwords, not a plugin.** Built into
WordPress core since 5.6 -- no extra plugin, just HTTP Basic Auth. The
category for each story is picked by asking Haiku to match it against the
site's actual live category list, not a hardcoded/guessed mapping.

**Every `cluster.py` run wipes `daily_stories`.** Cluster IDs are reassigned
from scratch every run and have no meaning across runs. Keeping old rows
around risks a future run's cluster `#5` silently overwriting a *different*
live WordPress post that an earlier run also happened to call `#5`. The
tradeoff: every full pipeline run creates fresh posts rather than ever
"updating" a previous run's post -- correct for a daily news roundup anyway.

**Cron, not a long-running scheduler process.** This is a once-a-day job --
cron survives reboots and needs no process to stay alive babysitting it. An
earlier `apscheduler`-based version was used only to test 30-minute interval
ingestion and was removed once the daily cron + `main.py` design replaced it.
