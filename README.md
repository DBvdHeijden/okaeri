# okaeri

おかえり ("welcome back"): a calm localhost homepage with the latest papers, blogs, forums and news in science and tech.
It fetches the sources you pick in the background and gathers them on one page, in tabs you set up yourself.

Each tab shows stories newest first, or recommended: a small embedding model on your machine learns from what you
open, like and hide, and puts the most relevant stories on top. Your reading history never leaves your device. 
Your recommendation algorithm is yours, tune it however you'd like. 

## Requirements

- macOS or Linux
- [uv](https://docs.astral.sh/uv/)
- ~500 MB disk: the Python environment and a local embedding model
- Internet for the first run (and for fetching feeds, of course)

## Install

```sh
git clone https://github.com/DBvdHeijden/okaeri.git && cd okaeri
uv run main.py install
```

Then open http://localhost:12362 and pick your sources. It runs in the background and starts whenever you log in; set it as your browser's homepage.

The first time, okaeri also downloads a language model (~330 MB) and indexes your articles in the background, which can take a few minutes. The feed works meanwhile; Settings (the gear) shows the progress until it's done.

## Update

```sh
uv run main.py update     # git pull, sync dependencies, restart
```

## Troubleshooting

```sh
uv run main.py status     # one screen with what's going on; share this when asking for help
uv run main.py logs       # the last 50 lines of data/okaeri.log
uv run main.py restart
```

## Uninstall

```sh
uv run main.py uninstall
```

This removes the background service and leaves your data alone; delete the folder to remove everything.

## Your data

Everything lives in the repo folder and is never committed: `data/` holds the database with your reading history, the embedding model and the log; `settings.json` holds your sources and tabs. It stays on your machine.

## Sources

Pick sources on the Settings page (the gear), or list their ids under `sources.enabled` in `settings.json`; the ids are in `catalog/sources.json`. To add a feed that isn't in the catalog, add an entry there (one medium and up to two topic tags from `catalog/tags.json`) and send it as a pull request, since `update` stops while you have local changes.

## Embedding model

New items are embedded locally with [EmbeddingGemma 2](https://huggingface.co/google/embeddinggemma-2) (downloaded on first use into `data/models/`, ~330 MB), licensed under the [Apache License 2.0](https://ai.google.dev/gemma/docs/gemma_4_license). Tabs set to “Recommended” rank by them: stories close to what you opened or liked go up, look-alikes of what you hid go down. Each topic has its own taste: liking AI stories lifts AI, without sinking politics.

## Development

```sh
uv run main.py                     # run in this terminal: http://127.0.0.1:12362
OKAERI_RELOAD=1 uv run main.py     # auto-reload while editing
OKAERI_FETCH=0 uv run main.py      # don't fetch feeds
OKAERI_DB=/tmp/x.db uv run main.py # default: data/okaeri.db
OKAERI_PORT=12363 uv run main.py   # another port; works for the service commands too
uv run pytest
```

On first run you're sent to onboarding: pick fields and media, then sources, then tick a few sample stories you'd read (saved as seed events for ranking), then tune the ranking dials while the top 5 stories change with them, then set up tabs. Nothing is fetched until you pick sources.

Embedding runs in a short-lived child process, `python -m app.embed`, so the server never holds the model in memory: the 270M text model, 8-bit ONNX from [onnx-community/embeddinggemma-2-ONNX](https://huggingface.co/onnx-community/embeddinggemma-2-ONNX), pinned to a revision, vectors cut to 256 dims and stored in SQLite. Try them out:

```sh
uv run scripts/similar.py "protein folding"   # feed items nearest to a search query
uv run scripts/similar.py --item <id>         # nearest to an article; the id is the one in /r/<id>
```

The favicons are drawn from the same Lorenz attractor as the homepage; regenerate them with `uv run scripts/make_favicon.py`.

Layout:

- `main.py`: runs the server (uvicorn on 127.0.0.1, one worker) and the service commands.
- `catalog/sources.json`: the curated source catalog.
- `catalog/tags.json`: the media (paper, blog, news, forum: each source is one, see `app/sources.py`), with their labels and how long their stories stay; and the topic tags.
- `settings.example.json`: copied to `settings.json` (gitignored) on first run; the onboarding page writes it. Tabs live here, edited in onboarding step 4 and in Settings: `{"builtin": "all"|"history", "hidden"}` or custom `{"name", "media", "topics", "sources", "hidden"}`. Each narrows the one before: the media, then the topics within those, then just the listed source ids. Leave one out and it doesn't narrow; nothing at all shows everything. All is always first and History last.
- `data/`: the SQLite database, downloaded models and the log (gitignored).
- `app/server.py`: routes. Every article list passes through `rank()`.
- `app/rank.py`: the ranking seam: Latest (recency) or Recommended (nearest opened/liked story in the same topics, minus the nearest hidden one, plus freshness, popularity and chance).
- `app/sources.py`: loads the catalog; `tags_for()`, `medium_of()` and tab matching.
- `app/fetch.py`: feed parsing (RSS/Atom, HF papers), conditional GET, and the background refresher.
- `app/embed.py`: loads the embedding model and embeds new items.
- `app/settings.py`: reads and writes `settings.json`.
- `app/store.py`: SQLite: items, per-feed cache headers, user events (click, hide, …) and embeddings.
- `app/templates/`, `app/static/`: server-rendered HTML, CSS, and a little vanilla JS.
