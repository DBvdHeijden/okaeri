# okaeri

おかえり: a minimal localhost homepage for following the latest papers, blogs, forums and news.

Right now it serves only the UI, using mock data. RSS fetching and ranking come later.

## Run

```sh
uv run okaeri            # http://localhost:8000
OKAERI_PORT=9000 uv run okaeri
OKAERI_RELOAD=1 uv run okaeri   # auto-reload while editing
```

## Test

```sh
uv run pytest
```

## Layout

- `okaeri/server.py`: routes. Every article list passes through `rank()`.
- `okaeri/rank.py`: the ranking seam. It currently sorts by recency.
- `okaeri/mock.py`: fake articles and sources.
- `okaeri/templates/`, `okaeri/static/`: server-rendered HTML, CSS, and a little vanilla JS.
