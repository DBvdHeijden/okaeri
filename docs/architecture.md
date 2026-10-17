# Architecture

okaeri is one Python process with one SQLite file. There's no build step, no framework on the frontend and no
server beyond your own machine.

```
feeds ──fetch.py──▶ SQLite ◀──embed.py (child process)
                      │
                   rank.py
                      │
        server.py + templates ──▶ browser
```

## The pieces

| File | Does |
|---|---|
| `main.py` | Starts the server, or installs it as a background service (launchd on macOS, systemd on Linux, Task Scheduler on Windows) |
| `app/server.py` | FastAPI routes: homepage, Settings, onboarding. Renders the Jinja templates |
| `app/fetch.py` | Background loop: every minute, fetches the sources that are due, then embeds new stories |
| `app/embed.py` | Turns stories into vectors with EmbeddingGemma, in a short-lived child process |
| `app/rank.py` | Orders every list of stories. See [ranking.md](ranking.md) |
| `app/store.py` | All SQL: stories, feed cache, events, embeddings |
| `app/settings.py` | Reads and writes `settings.json` |
| `app/sources.py` | Loads the catalog: sources, media, topics, languages |
| `app/templates/`, `app/static/` | Server-rendered HTML, one stylesheet, a little vanilla JS |

## Data

Everything lives on your machine:

- **`data/okaeri.db`** (SQLite) holds:
  - `items`: fetched stories. The same link from two sources is one story.
  - `feeds`: ETag and Last-Modified for each feed, so we only download what changed.
  - `events`: every open, like, hide and undo.
  - `embeddings`: a vector per story (and per interest text), for each model.
- **`settings.json`**: your sources, tabs, ranking dials and onboarding answers. Missing keys fall back to
  `settings.example.json`.
- **`catalog/`**: the sources (`sources.json`) and the media, topics and languages (`tags.json`). They're in the
  repo, not in your data.

## How a story gets to the page

1. **Fetch.** The refresher wakes every minute and fetches the selected sources whose `refresh_minutes` have
   passed. Each fetch is a conditional GET, and one failing feed doesn't stop the others.
2. **Embed.** If there are stories without a vector, `python -m app.embed` runs as a separate process, embeds
   them and exits.
3. **Read.** A page load reads stories from the tab's sources, and keeps only those younger than their medium's
   `max_age_days`.
4. **Rank.** `rank()` sorts them by Latest or Recommended.
5. **Render.** A Jinja template renders the page.

## Why it's built this way

- **One process, one file.** Running `uv run main.py` is the whole install. Backup is copying `data/`.
- **Embedding in a child process.** The model needs about 1.3 GB while it runs. In a child process, that memory is
  released when it exits, instead of being held by the server all day. It also runs at low priority (`nice` on
  macOS and Linux, idle priority on Windows), so it doesn't slow down whatever else you're doing. The model is
  EmbeddingGemma 2 (270M), as 8-bit ONNX from [onnx-community/embeddinggemma-2-ONNX](https://huggingface.co/onnx-community/embeddinggemma-2-ONNX),
  pinned to a revision. Its vectors are cut to 256 dimensions and stored in SQLite.
- **Events are only ever added, never edited.** Undoing a like adds an `unseed` event; nothing is deleted. Ranking
  replays the log, so your history stays complete and nothing else has to stay in sync with it.
- **Age limits apply when reading, not when fetching.** Changing a medium's `max_age_days` takes effect on the
  next page load, without fetching again.
- **Server-rendered pages.** Pages work without JS. JS only adds small touches (transitions, the theme toggle,
  rating without a reload).
