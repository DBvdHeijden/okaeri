# Contributing

Thanks for helping out. okaeri stays small on purpose, so the bar is: does this make it simpler or clearly better?

## Getting started

```sh
git clone git@github.com:DBvdHeijden/okaeri.git && cd okaeri
uv run main.py                     # run in this terminal: http://127.0.0.1:12362
OKAERI_DB=/tmp/x.db uv run main.py # a separate database, so your own history stays clean (default: data/okaeri.db)
OKAERI_RELOAD=1 uv run main.py     # auto-reload while editing
OKAERI_FETCH=0 uv run main.py      # don't fetch feeds
OKAERI_PORT=12363 uv run main.py   # another port; works for the service commands too
uv run pytest
```

On first run you're sent to onboarding. Nothing is fetched until you pick sources.

To see what the embeddings consider close:

```sh
uv run scripts/similar.py "protein folding"   # feed items nearest to a search query
uv run scripts/similar.py --item <id>         # nearest to an article; the id is the one in /r/<id>
```

[docs/architecture.md](docs/architecture.md) shows how the pieces fit together.

## How we write code

The full rules are in [AGENTS.md](AGENTS.md). They're written for AI coding agents, but apply to everyone. In short:

- Simple beats clever. Write the obvious version first.
- Standard library first. Add a dependency only when it saves real effort.
- Comment the *why*, never the *what*.
- Only handle errors at real boundaries (network, files, user input).
- No frontend framework and no build step.

## Working with AI

Using an AI agent or vibe coding is fine. A lot of okaeri was built that way. But you own what you push:

- **Read and understand every line.** If you can't explain why a line is there, it shouldn't be in the PR.
- **Check that it works.** Run it, click through what changed, run the tests. Don't trust the agent saying it's done.
- **Keep the diff to the task.** No sweeping refactors, renames or "cleanups" without a clear reason, stated in
  the PR. A big diff with an unclear purpose gets closed, however tidy it looks.
- **Point your agent at [AGENTS.md](AGENTS.md).** Most tools read it on their own. For Claude Code, put
  `@AGENTS.md` in a `CLAUDE.md`.

## Common changes

- **Adding a source:** add an entry to `catalog/sources.json`, with one medium and up to two topics from
  `catalog/tags.json`. Then run `uv run scripts/sample_sources.py`, so onboarding can match against its titles.
- **Changing the ranking:** all of it goes through `rank()` in `app/rank.py`. Update
  [docs/ranking.md](docs/ranking.md) in the same PR.

## Pull requests

- Branch from `main`, and keep to one change per PR.
- Say what changed and why. Add a screenshot if it's visible on the page.
- Run `uv run pytest` before you push.
