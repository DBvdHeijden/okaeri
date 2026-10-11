"""Feed fetching and the background refresh loop.

Modelled on glance's RSS widget: conditional GET with ETag/Last-Modified, per-feed
limits, absolute links, and one failing feed never takes the others down.
"""

import asyncio
import html
import logging
import re
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from time import struct_time
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit

import feedparser
import httpx

from okaeri.models import FetchedItem, Source
from okaeri.store import Store

log = logging.getLogger("okaeri.fetch")

USER_AGENT = "okaeri/0.1 (+https://github.com/DBvdHeijden/okaeri)"
PER_SOURCE_LIMIT = 30  # newest items kept per fetch; stops arXiv/OpenAI archives flooding
MAX_AGE = timedelta(days=14)
CONCURRENCY = 8
HOST_INTERVAL = {"export.arxiv.org": 3.0}  # arXiv API asks for >= 3s between requests
TICK_SECONDS = 60

# --- normalisation -----------------------------------------------------------

_ARXIV_ID = re.compile(r"(\d{4}\.\d{4,5})(?:v\d+)?")
_TRACKING = {"ref", "source", "fbclid", "gclid"}
_TAGS = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")


def item_key(url: str) -> str:
    """Normalise a URL so the same story from different sources compares equal."""
    parts = urlsplit(url.strip())
    host = parts.netloc.lower().removeprefix("www.")
    path = parts.path.rstrip("/")
    if host in ("arxiv.org", "export.arxiv.org") or (host == "huggingface.co" and path.startswith("/papers/")):
        if m := _ARXIV_ID.search(path):
            return f"arxiv:{m.group(1)}"
    query = urlencode(sorted(
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not (k.lower().startswith("utm_") or k.lower() in _TRACKING)
    ))
    return f"{host}{path}" + (f"?{query}" if query else "")


def clean_text(text: str, limit: int) -> str:
    text = _SPACE.sub(" ", html.unescape(_TAGS.sub(" ", text or ""))).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _to_datetime(t: struct_time | None) -> datetime | None:
    return datetime(*t[:6], tzinfo=UTC) if t else None  # feedparser normalises to UTC


def _keep_recent(items: list[FetchedItem], now: datetime) -> list[FetchedItem]:
    items = [i for i in items if i.published_at >= now - MAX_AGE]
    items.sort(key=lambda i: i.published_at, reverse=True)
    return items[:PER_SOURCE_LIMIT]


# --- parsers -----------------------------------------------------------------


def parse_feed(content: bytes, source: Source, now: datetime | None = None) -> list[FetchedItem]:
    now = now or datetime.now(UTC)
    feed = feedparser.parse(content)
    if feed.bozo and not feed.entries:
        raise ValueError(f"unparseable feed: {feed.get('bozo_exception')}")
    base = feed.feed.get("link") or source.url

    items = []
    for entry in feed.entries:
        link = entry.get("link")
        if not link:
            continue
        url = urljoin(base, link)
        summary = clean_text(entry.get("summary", ""), 600)
        if summary.lower() == "comments":  # HN/Lobsters put only a comments link here
            summary = ""
        title = clean_text(entry.get("title", ""), 300) or clean_text(summary, 100)
        if not title:
            continue
        published = _to_datetime(entry.get("published_parsed") or entry.get("updated_parsed")) or now
        items.append(FetchedItem(
            key=item_key(url),
            url=url,
            title=title,
            published_at=published,
            summary=summary,
            discussion_url=entry.get("comments"),
        ))
    return _keep_recent(items, now)


def parse_hf_papers(data: list[dict], now: datetime | None = None) -> list[FetchedItem]:
    now = now or datetime.now(UTC)
    items = []
    for entry in data:
        paper = entry.get("paper") or {}
        paper_id, title = paper.get("id"), entry.get("title") or paper.get("title")
        if not paper_id or not title:
            continue
        url = f"https://huggingface.co/papers/{paper_id}"
        published = entry.get("publishedAt") or paper.get("publishedAt")
        items.append(FetchedItem(
            key=item_key(url),
            url=url,
            title=clean_text(title, 300),
            published_at=datetime.fromisoformat(published.replace("Z", "+00:00")) if published else now,
            summary=clean_text(entry.get("summary") or paper.get("summary", ""), 600),
            discussion_url=url,
        ))
    return _keep_recent(items, now)


# --- fetching ----------------------------------------------------------------


async def fetch_source(client: httpx.AsyncClient, source: Source, store: Store) -> None:
    etag, last_modified = store.cache_headers(source.id)
    headers = {}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified

    resp = await client.get(source.url, headers=headers)
    if resp.status_code == 304:
        store.save_fetch(source.id, None, etag, last_modified)
        return
    resp.raise_for_status()

    if source.fetcher == "hf_papers":
        items = parse_hf_papers(resp.json())
    else:
        items = parse_feed(resp.content, source)
    store.save_fetch(source.id, items, resp.headers.get("ETag"), resp.headers.get("Last-Modified"))
    log.info("fetched %s: %d items", source.id, len(items))


async def refresh(store: Store, sources: list[Source]) -> None:
    """Fetch sources concurrently; one host at a time per host, politely spaced."""
    by_host: dict[str, list[Source]] = defaultdict(list)
    for s in sources:
        by_host[urlsplit(s.url).netloc].append(s)

    limit = asyncio.Semaphore(CONCURRENCY)

    async def run_host(client: httpx.AsyncClient, host: str, queue: list[Source]) -> None:
        for n, source in enumerate(queue):
            if n:
                await asyncio.sleep(HOST_INTERVAL.get(host, 0.5))
            async with limit:
                try:
                    await fetch_source(client, source, store)
                except Exception as exc:  # noqa: BLE001 — a bad feed must not stop the rest
                    log.warning("failed to fetch %s: %s", source.id, exc)
                    store.save_error(source.id, f"{type(exc).__name__}: {exc}")

    async with httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT},
        timeout=httpx.Timeout(15.0),
        follow_redirects=True,
    ) as client:
        await asyncio.gather(*(run_host(client, h, q) for h, q in by_host.items()))
    store.prune()


class Refresher:
    """Background loop: every minute, fetch whichever selected sources are due."""

    def __init__(self, store: Store, catalogue: dict[str, Source]):
        self.store = store
        self.catalogue = catalogue
        self.wake = asyncio.Event()

    async def run(self) -> None:
        while True:
            try:
                selected = [self.catalogue[i] for i in self.store.selected() if i in self.catalogue]
                if due := self.store.due(selected):
                    await refresh(self.store, due)
            except Exception:
                log.exception("refresh cycle failed")
            try:
                await asyncio.wait_for(self.wake.wait(), TICK_SECONDS)
            except TimeoutError:
                pass
            self.wake.clear()
