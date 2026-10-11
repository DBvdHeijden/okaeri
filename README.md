# okaeri

おかえり: a minimal localhost homepage for following the latest papers, blogs, forums and news.

It fetches a curated set of science and tech feeds in the background and stores them in SQLite. Ranking is plain recency for now; embedding-based ranking comes later.

## Run

```sh
uv run main.py                     # http://127.0.0.1:12362
OKAERI_RELOAD=1 uv run main.py     # auto-reload while editing
OKAERI_FETCH=0 uv run main.py      # don't fetch feeds
OKAERI_DB=/tmp/x.db uv run main.py # default: data/okaeri.db
```

On first run you're sent to onboarding to pick sources; nothing is fetched until you do.

## Test

```sh
uv run pytest
```

## Favicon

The favicons are drawn from the same Lorenz attractor as the homepage. Regenerate them with:

```sh
uv run scripts/make_favicon.py
```

## Layout

- `main.py`: starts uvicorn on 127.0.0.1:12362, one worker.
- `catalog/sources.json`: the curated source catalog.
- `catalog/tags.json`: the tag vocabulary: formats (paper, blog, forum, news) and topics.
- `settings.example.json`: copied to `settings.json` (gitignored) on first run; the onboarding page writes it. Tabs live here as `{"name", "tags"}`.
- `data/`: the SQLite database (gitignored).
- `app/server.py`: routes. Every article list passes through `rank()`.
- `app/rank.py`: the ranking seam. It currently sorts by recency.
- `app/sources.py`: loads the catalog; `tags_for()`, `format_of()` and tab matching.
- `app/fetch.py`: feed parsing (RSS/Atom, HF papers), conditional GET, and the background refresher.
- `app/settings.py`: reads and writes `settings.json`.
- `app/store.py`: SQLite: items, per-feed cache headers, and user events (click, hide, …).
- `app/templates/`, `app/static/`: server-rendered HTML, CSS, and a little vanilla JS.
