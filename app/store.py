"""SQLite storage: fetched items, per-feed HTTP cache state, and user events."""

import hashlib
from dataclasses import replace
import os
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from functools import cache
from pathlib import Path

from app import ROOT
from app.models import Article, Event, FetchedItem, Source
from app.sources import MEDIA

# Everything the user did, by story key: the History tab and the signal for ranking.
EVENTS = """
CREATE TABLE IF NOT EXISTS events (
    id   INTEGER PRIMARY KEY,
    type TEXT NOT NULL CHECK (type IN ('seed', 'unseed', 'click', 'hide', 'unhide')),
    key  TEXT NOT NULL,
    at   TEXT NOT NULL
)"""

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS items (
    source_id      TEXT NOT NULL,
    key            TEXT NOT NULL,
    id             TEXT NOT NULL,  -- article_id(key), for /r/{{id}} and /hide/{{id}}
    url            TEXT NOT NULL,
    title          TEXT NOT NULL,
    summary        TEXT NOT NULL DEFAULT '',
    discussion_url TEXT,
    published_at   TEXT NOT NULL,
    fetched_at     TEXT NOT NULL,
    score          INTEGER,
    comments       INTEGER,
    PRIMARY KEY (source_id, key)
);
CREATE INDEX IF NOT EXISTS items_published_at ON items (published_at);
CREATE INDEX IF NOT EXISTS items_key ON items (key);

CREATE TABLE IF NOT EXISTS feeds (
    source_id     TEXT PRIMARY KEY,
    etag          TEXT,
    last_modified TEXT,
    fetched_at    TEXT NOT NULL,
    error         TEXT
);

-- The selection moved to settings.json.
DROP TABLE IF EXISTS selected_sources;

{EVENTS};
CREATE INDEX IF NOT EXISTS events_key ON events (key);

-- One float32 vector per story key and model; model names the dims too, e.g. embeddinggemma-2-text@256.
CREATE TABLE IF NOT EXISTS embeddings (
    key    TEXT NOT NULL,
    model  TEXT NOT NULL,
    vector BLOB NOT NULL,
    PRIMARY KEY (key, model)
);

-- The outcome of the last background embed run, for `main.py status`. One row.
CREATE TABLE IF NOT EXISTS last_embed_run (
    id     INTEGER PRIMARY KEY CHECK (id = 1),
    at     TEXT NOT NULL,
    result TEXT NOT NULL
);
"""

# Columns added after the first release; added in place to existing databases.
MIGRATIONS = {"items": {"score": "INTEGER", "comments": "INTEGER", "id": "TEXT"}}

# When the same story comes from several sources, the medium first in catalog/tags.json is shown;
# the others become "also on". Forums last: they mostly link to someone else's post.
PRIMARY_ORDER = {medium: i for i, medium in enumerate(MEDIA)}


def _same_publisher(a: str, b: str) -> bool:
    """BBC Science / BBC World, NOS Tech / NOS Nieuws, arXiv cs.LG / arXiv cs.AI."""
    return a.split()[0] == b.split()[0]


def article_id(key: str) -> str:
    return hashlib.sha1(key.encode()).hexdigest()[:12]


def default_path() -> Path:
    if env := os.environ.get("OKAERI_DB"):
        return Path(env)
    return ROOT / "data" / "okaeri.db"


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat()


class Store:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(SCHEMA)
            if "'unseed'" not in db.execute("SELECT sql FROM sqlite_master WHERE name = 'events'").fetchone()[0]:
                # SQLite can't change a CHECK in place: move the events into a table that allows the new type.
                db.execute("BEGIN")
                db.execute("ALTER TABLE events RENAME TO events_old")
                db.execute(EVENTS)
                db.execute("INSERT INTO events SELECT * FROM events_old")
                db.execute("DROP TABLE events_old")
                db.execute("CREATE INDEX events_key ON events (key)")
            for table, columns in MIGRATIONS.items():
                have = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
                for name, decl in columns.items():
                    if name not in have:
                        db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
            keys = db.execute("SELECT DISTINCT key FROM items WHERE id IS NULL").fetchall()
            db.executemany("UPDATE items SET id = ? WHERE key = ?", [(article_id(k), k) for k, in keys])
            db.execute("CREATE INDEX IF NOT EXISTS items_id ON items (id)")
            if db.execute("SELECT 1 FROM sqlite_master WHERE name = 'clicks'").fetchone():
                db.execute("INSERT INTO events (type, key, at) SELECT 'click', key, clicked_at FROM clicks ORDER BY id")
                db.execute("DROP TABLE clicks")

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path)
        try:
            with db:
                yield db
        finally:
            db.close()

    # Feed state

    def cache_headers(self, source_id: str) -> tuple[str | None, str | None]:
        with self._conn() as db:
            row = db.execute("SELECT etag, last_modified FROM feeds WHERE source_id = ?", (source_id,)).fetchone()
        return row if row else (None, None)

    def due(self, sources: Iterable[Source], now: datetime | None = None) -> list[Source]:
        now = now or datetime.now(UTC)
        with self._conn() as db:
            last = dict(db.execute("SELECT source_id, fetched_at FROM feeds"))
        return [
            s for s in sources
            if s.id not in last
            or datetime.fromisoformat(last[s.id]) + timedelta(minutes=s.refresh_minutes) <= now
        ]

    def pending(self, source_ids: Iterable[str]) -> bool:
        """True if any of these sources has never been fetched."""
        ids = set(source_ids)
        if not ids:
            return False
        with self._conn() as db:
            fetched = {row[0] for row in db.execute("SELECT source_id FROM feeds")}
        return bool(ids - fetched)

    def save_fetch(
        self,
        source_id: str,
        items: list[FetchedItem] | None,
        etag: str | None,
        last_modified: str | None,
    ) -> None:
        """Record a successful fetch. items=None means 304 Not Modified."""
        now = _iso(datetime.now(UTC))
        with self._conn() as db:
            if items:
                db.executemany(
                    """
                    INSERT INTO items (source_id, key, id, url, title, summary, discussion_url, published_at,
                                       fetched_at, score, comments)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (source_id, key) DO UPDATE SET
                        url = excluded.url, title = excluded.title, summary = excluded.summary,
                        discussion_url = excluded.discussion_url, fetched_at = excluded.fetched_at,
                        score = excluded.score, comments = excluded.comments
                    """,  # published_at is kept from first sight, so undated items don't float up
                    [
                        (source_id, i.key, article_id(i.key), i.url, i.title, i.summary, i.discussion_url, _iso(i.published_at),
                         now, i.score, i.comments)
                        for i in items
                    ],
                )
            db.execute(
                """
                INSERT INTO feeds (source_id, etag, last_modified, fetched_at, error) VALUES (?, ?, ?, ?, NULL)
                ON CONFLICT (source_id) DO UPDATE SET
                    etag = coalesce(excluded.etag, feeds.etag),
                    last_modified = coalesce(excluded.last_modified, feeds.last_modified),
                    fetched_at = excluded.fetched_at, error = NULL
                """,
                (source_id, etag, last_modified, now),
            )

    def last_fetch(self) -> tuple[str | None, int]:
        """When any feed was last fetched, and how many feeds failed on their last try."""
        with self._conn() as db:
            return db.execute("SELECT max(fetched_at), count(error) FROM feeds").fetchone()

    def save_error(self, source_id: str, error: str) -> None:
        now = _iso(datetime.now(UTC))
        with self._conn() as db:
            db.execute(
                """
                INSERT INTO feeds (source_id, fetched_at, error) VALUES (?, ?, ?)
                ON CONFLICT (source_id) DO UPDATE SET fetched_at = excluded.fetched_at, error = excluded.error
                """,
                (source_id, now, error[:500]),
            )

    def prune(self, max_age_days: int = max(m["max_age_days"] for m in MEDIA.values()) + 30) -> None:
        cutoff = _iso(datetime.now(UTC) - timedelta(days=max_age_days))
        with self._conn() as db:
            db.execute("DELETE FROM items WHERE published_at < ? AND key NOT IN (SELECT key FROM events)", (cutoff,))
            db.execute("DELETE FROM embeddings WHERE key NOT IN (SELECT key FROM items)")

    # Embeddings

    def embedded_keys(self, model: str) -> set[str]:
        with self._conn() as db:
            return {key for key, in db.execute("SELECT key FROM embeddings WHERE model = ?", (model,))}

    def save_embeddings(self, model: str, rows: list[tuple[str, bytes]]) -> None:
        with self._conn() as db:
            db.executemany(
                "INSERT OR REPLACE INTO embeddings (key, model, vector) VALUES (?, ?, ?)",
                [(key, model, vector) for key, vector in rows],
            )

    def save_embed_run(self, result: str) -> None:
        with self._conn() as db:
            db.execute(
                "INSERT OR REPLACE INTO last_embed_run (id, at, result) VALUES (1, ?, ?)",
                (_iso(datetime.now(UTC)), result),
            )

    def last_embed_run(self) -> tuple[str, str] | None:
        with self._conn() as db:
            return db.execute("SELECT at, result FROM last_embed_run").fetchone()

    def embeddings(self, model: str) -> dict[str, bytes]:
        with self._conn() as db:
            return dict(db.execute("SELECT key, vector FROM embeddings WHERE model = ?", (model,)))

    # Events / History

    def add_event(self, type: str, key: str) -> None:
        with self._conn() as db:
            db.execute("INSERT INTO events (type, key, at) VALUES (?, ?, ?)", (type, key, _iso(datetime.now(UTC))))

    def clear_events(self) -> None:
        with self._conn() as db:
            db.execute("DELETE FROM events")

    def events(self) -> list[Event]:
        with self._conn() as db:
            rows = db.execute("SELECT type, key, at FROM events ORDER BY id").fetchall()
        return [Event(type, key, datetime.fromisoformat(at)) for type, key, at in rows]

    def article(self, id: str, sources: dict[str, Source]) -> Article | None:
        with self._conn() as db:
            rows = db.execute(
                """
                SELECT source_id, key, url, title, summary, discussion_url, published_at, score, comments
                FROM items WHERE id = ?
                """,
                (id,),
            ).fetchall()
        rows = [r for r in rows if r[0] in sources]
        return _merge({rows[0][1]: rows}, sources)[0] if rows else None

    def stories(self, times: dict[str, datetime], sources: dict[str, Source]) -> list[Article]:
        """These stories in the given order, each with published_at set to its time (when opened, liked or hidden)."""
        keys = ",".join("?" * len(times))
        with self._conn() as db:
            rows = db.execute(
                f"""
                SELECT source_id, key, url, title, summary, discussion_url, published_at, score, comments
                FROM items WHERE key IN ({keys})
                """,
                list(times),
            ).fetchall()
        groups: dict[str, list[tuple]] = {}
        for row in rows:
            if row[0] in sources:
                groups.setdefault(row[1], []).append(row)
        by_key = {a.key: a for a in _merge(groups, sources)}
        return [replace(by_key[key], published_at=at) for key, at in times.items() if key in by_key]

    # Reading

    def articles(self, sources: dict[str, Source]) -> list[Article]:
        """Stories from the given sources, merged across sources by key. Unranked.

        Each source's items are limited to its medium's max_age_days.
        """
        if not sources:
            return []
        now = datetime.now(UTC)
        cutoffs = {i: _iso(now - timedelta(days=MEDIA[s.medium]["max_age_days"])) for i, s in sources.items()}
        cutoff = min(cutoffs.values())
        marks = ",".join("?" * len(sources))
        with self._conn() as db:
            rows = db.execute(
                f"""
                SELECT source_id, key, url, title, summary, discussion_url, published_at, score, comments
                FROM items
                WHERE source_id IN ({marks}) AND published_at >= ?
                """,
                [*sources, cutoff],
            ).fetchall()

        groups: dict[str, list[tuple]] = {}
        for row in rows:
            if row[6] >= cutoffs[row[0]]:
                groups.setdefault(row[1], []).append(row)
        return _merge(groups, sources)


def _merge(groups: dict[str, list[tuple]], sources: dict[str, Source]) -> list[Article]:
    """One Article per key from its item rows across sources."""
    articles = []
    for key, group in groups.items():
        group.sort(key=lambda r: (PRIMARY_ORDER[sources[r[0]].medium], r[6]))
        source_id, _, url, title, summary, discussion_url, published_at, score, comments = group[0]
        primary = sources[source_id]
        also_on = tuple(dict.fromkeys(
            sources[r[0]].name for r in group[1:]
            if not _same_publisher(sources[r[0]].name, primary.name)
        ))
        # Counts and the discussion link come from the busiest discussion of the story.
        counted = [r for r in group if r[7] is not None or r[8] is not None]
        if counted:
            busiest = max(counted, key=lambda r: ((r[8] or 0), (r[7] or 0)))
            score, comments = busiest[7], busiest[8]
            discussion_url = busiest[5] or discussion_url
        if not discussion_url:
            discussion_url = next((r[5] for r in group if r[5]), None)
        articles.append(Article(
            id=article_id(key),
            key=key,
            title=title,
            url=url,
            source=primary.name,
            source_id=source_id,
            published_at=datetime.fromisoformat(published_at),
            also_on=also_on,
            discussion_url=discussion_url,
            score=score,
            comments=comments,
            summary=summary,
            source_ids=tuple(dict.fromkeys(r[0] for r in group)),
        ))
    return articles


@cache
def open_store(path: Path) -> Store:
    return Store(path)
