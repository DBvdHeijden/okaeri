# okaeri

おかえり: a minimal localhost homepage for following the latest papers, blogs, forums and news.

It fetches a curated set of science and tech feeds in the background and stores them in SQLite. Ranking is plain recency for now; embedding-based ranking comes later.

## Run

```sh
uv run okaeri            # http://localhost:8000
OKAERI_PORT=9000 uv run okaeri
OKAERI_RELOAD=1 uv run okaeri   # auto-reload while editing
OKAERI_FETCH=0 uv run okaeri    # don't fetch feeds
OKAERI_DB=/tmp/x.db uv run okaeri  # default: ~/.local/share/okaeri/okaeri.db
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

- `okaeri/server.py`: routes. Every article list passes through `rank()`.
- `okaeri/rank.py`: the ranking seam. It currently sorts by recency.
- `okaeri/sources.py`: the curated source catalogue.
- `okaeri/fetch.py`: feed parsing (RSS/Atom, HF papers), conditional GET, and the background refresher.
- `okaeri/store.py`: SQLite: items, per-feed cache headers, and the selected sources.
- `okaeri/templates/`, `okaeri/static/`: server-rendered HTML, CSS, and a little vanilla JS.
