# AGENTS.md

How to work on okaeri, for AI coding agents and the people steering them.

Okaeri: a minimal localhost homepage for science & tech feeds.
Python + FastAPI + Jinja2, SQLite, vanilla JS. One repo, one process, `uv run main.py`.
How it fits together: `docs/architecture.md`. How ranking works: `docs/ranking.md`.
Run `uv run pytest` before you call a change done.

## How to write code here

- Simple beats clever. Write the obvious version first.
- Fewer lines is better, as long as it stays easy to read.
- Small functions with clear names. Names should make comments unnecessary.
- Comment only the *why*, never the *what*. No docstrings on obvious functions.
- Flat over nested: return early, avoid deep if/else chains.
- Plain functions and dicts/dataclasses. Classes only when state really needs one.
- No abstractions for things that exist once. Generalize on the third use, not the first.
- Standard library first. Add a dependency only if it saves real effort.
- Type hints on function signatures; skip them where they add noise.

## What not to do

- Don't be defensive. No try/except around things that shouldn't fail; let errors surface.
- Only handle errors at real boundaries: network, file I/O, user input.
- No validation layers, wrappers, or config options "just in case".
- No logging noise. Log failures that matter, nothing else.
- Don't add tests, docs, or files unless asked.
- Don't refactor code unrelated to the task.

## Frontend

- Server-rendered templates. No framework, no build step.
- JS only for small interactions (hide, theme toggle). Keep it tiny and inline-readable.
- CSS variables for colors; one stylesheet.

## Structure

- Ranking always goes through `rank()` in `app/rank.py`; never rank in routes or templates. Keep `docs/ranking.md` in step.
- SQL lives in plain strings near where it's used. No ORM.

## When in doubt

Pick the version a newcomer would understand fastest.