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

On first run you're sent to onboarding: pick fields and formats, then sources, then tick a few sample stories you'd read (saved as seed events for ranking). Nothing is fetched until you pick sources. Afterwards the gear opens Settings, where you change which sources you follow or redo onboarding from your current answers.

## Test

```sh
uv run pytest
```

## Embeddings (experiment)

After each refresh, new feed items (and anything you clicked, hid or seeded) are embedded with [EmbeddingGemma 2](https://huggingface.co/google/embeddinggemma-2), run locally: the 270M text model, 8-bit ONNX from [onnx-community/embeddinggemma-2-ONNX](https://huggingface.co/onnx-community/embeddinggemma-2-ONNX), pinned to a revision and downloaded on first use into `data/models/` (~330 MB). Vectors are cut to 256 dims and stored in SQLite. Ranking doesn't use them yet. The model is licensed under the [Apache License 2.0](https://ai.google.dev/gemma/docs/gemma_4_license) (the linked page is the plain Apache 2.0 text, not the Gemma Terms of Use).

Try them out:

```sh
uv run scripts/similar.py "protein folding"   # feed items nearest to a search query
uv run scripts/similar.py --item <id>         # nearest to an article; the id is the one in /r/<id>
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
- `settings.example.json`: copied to `settings.json` (gitignored) on first run; the onboarding page writes it. Tabs live here, edited from Settings: `{"builtin": "all"|"history", "hidden"}` or custom `{"name", "tags", "hidden"}` (no tags shows everything). All is always first and History last.
- `data/`: the SQLite database and downloaded models (gitignored).
- `app/server.py`: routes. Every article list passes through `rank()`.
- `app/rank.py`: the ranking seam. It currently sorts by recency.
- `app/sources.py`: loads the catalog; `tags_for()`, `format_of()` and tab matching.
- `app/fetch.py`: feed parsing (RSS/Atom, HF papers), conditional GET, and the background refresher.
- `app/embed.py`: loads the embedding model and embeds new items.
- `app/settings.py`: reads and writes `settings.json`.
- `app/store.py`: SQLite: items, per-feed cache headers, user events (click, hide, …) and embeddings.
- `app/templates/`, `app/static/`: server-rendered HTML, CSS, and a little vanilla JS.
