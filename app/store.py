"""SQLite storage: fetched items, per-feed HTTP cache state, and the source selection."""

import hashlib
import os
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from functools import cache
from pathlib import Path

from app import ROOT
from app.models import KINDS, MAX_AGE_DAYS, Article, FetchedItem, Source

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    source_id      TEXT NOT NULL,
    key            TEXT NOT NULL,
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

CREATE TABLE IF NOT EXISTS selected_sources (
    source_id TEXT PRIMARY KEY
);

-- Stories the user opened. A snapshot, so History outlives pruned items;
-- also the interest signal for ranking later.
CREATE TABLE IF NOT EXISTS clicks (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    key        TEXT NOT NULL,
    url        TEXT NOT NULL,
    title      TEXT NOT NULL,
    source     TEXT NOT NULL,
    kind       TEXT NOT NULL,
    clicked_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS clicks_clicked_at ON clicks (clicked_at);
"""

# Columns added after the first release; added in place to existing databases.
MIGRATIONS = {"items": {"score": "INTEGER", "comments": "INTEGER"}}

# When the same story comes from several sources, the first kind here is shown;
# the others become "also on". Forums last: they mostly link to someone else's post.
PRIMARY_ORDER = {kind: i for i, kind in enumerate(("paper", "blog", "scitech", "news", "forum"))}
assert set(PRIMARY_ORDER) == set(KINDS)


def _same_publisher(a: str, b: str) -> bool:
    """BBC Science / BBC World, NOS Tech / NOS Nieuws, arXiv cs.LG / arXiv cs.AI."""
    return a.split()[0] == b.split()[0]


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
            for table, columns in MIGRATIONS.items():
                have = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
                for name, decl in columns.items():
                    if name not in have:
                        db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path)
        try:
            with db:
                yield db
        finally:
            db.close()

    # Selection

    def selected(self) -> set[str]:
        with self._conn() as db:
            return {row[0] for row in db.execute("SELECT source_id FROM selected_sources")}

    def set_selected(self, source_ids: Iterable[str]) -> None:
        with self._conn() as db:
            db.execute("DELETE FROM selected_sources")
            db.executemany("INSERT INTO selected_sources VALUES (?)", [(i,) for i in set(source_ids)])

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
                    INSERT INTO items (source_id, key, url, title, summary, discussion_url, published_at,
                                       fetched_at, score, comments)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (source_id, key) DO UPDATE SET
                        url = excluded.url, title = excluded.title, summary = excluded.summary,
                        discussion_url = excluded.discussion_url, fetched_at = excluded.fetched_at,
                        score = excluded.score, comments = excluded.comments
                    """,  # published_at is kept from first sight, so undated items don't float up
                    [
                        (source_id, i.key, i.url, i.title, i.summary, i.discussion_url, _iso(i.published_at),
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

    def prune(self, max_age_days: int = max(MAX_AGE_DAYS.values()) + 30) -> None:
        cutoff = _iso(datetime.now(UTC) - timedelta(days=max_age_days))
        with self._conn() as db:
            db.execute("DELETE FROM items WHERE published_at < ?", (cutoff,))

    # Clicks / History

    def record_click(self, key: str, url: str, title: str, source: str, kind: str) -> None:
        with self._conn() as db:
            db.execute(
                "INSERT INTO clicks (key, url, title, source, kind, clicked_at) VALUES (?, ?, ?, ?, ?, ?)",
                (key, url, title, source, kind, _iso(datetime.now(UTC))),
            )

    def history(self, limit: int = 100) -> list[Article]:
        """Opened stories, most recently opened first; each story once."""
        with self._conn() as db:
            rows = db.execute(
                """
                SELECT key, url, title, source, kind, max(clicked_at) AS last FROM clicks
                GROUP BY key ORDER BY last DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            Article(
                id=hashlib.sha1(key.encode()).hexdigest()[:12],
                key=key, url=url, title=title, source=source, kind=kind,
                published_at=datetime.fromisoformat(last),
            )
            for key, url, title, source, kind, last in rows
        ]

    # Reading

    def articles(self, sources: dict[str, Source]) -> list[Article]:
        """Stories from the given sources, merged across sources by key. Unranked.

        Each source's items are limited to its kind's MAX_AGE_DAYS.
        """
        if not sources:
            return []
        now = datetime.now(UTC)
        cutoffs = {i: _iso(now - timedelta(days=MAX_AGE_DAYS[s.kind])) for i, s in sources.items()}
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

        articles = []
        for key, group in groups.items():
            group.sort(key=lambda r: (PRIMARY_ORDER[sources[r[0]].kind], r[6]))
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
                id=hashlib.sha1(key.encode()).hexdigest()[:12],
                key=key,
                title=title,
                url=url,
                source=primary.name,
                kind=primary.kind,
                published_at=datetime.fromisoformat(published_at),
                also_on=also_on,
                discussion_url=discussion_url,
                score=score,
                comments=comments,
                summary=summary,
            ))
        return articles


@cache
def open_store(path: Path) -> Store:
    return Store(path)
