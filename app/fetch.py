"""Feed fetching and the background refresh loop.

Modelled on glance's RSS widget: conditional GET with ETag/Last-Modified, per-feed
limits, absolute links, and one failing feed never takes the others down.
"""

import asyncio
import html
import logging
import re
import sys
import time
from collections import defaultdict
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from time import struct_time
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit

import feedparser
import httpx

from app import ROOT, settings
from app.embed import pending
from app.models import MAX_AGE_DAYS, FetchedItem, Source
from app.store import Store

log = logging.getLogger("okaeri.fetch")

USER_AGENT = "okaeri/0.1 (+https://github.com/DBvdHeijden/okaeri)"
PER_SOURCE_LIMIT = 30  # newest items kept per fetch; stops arXiv/OpenAI archives flooding
MAX_AGE = timedelta(days=max(MAX_AGE_DAYS.values()))  # per-format limits are applied when reading
CONCURRENCY = 8
HOST_INTERVAL = {"export.arxiv.org": 3.0}  # arXiv API asks for >= 3s between requests
TICK_SECONDS = 60
EMBED_TIMEOUT_SECONDS = 600
EMBED_RETRY_SECONDS = 1800  # after a failure; each try loads a ~1.3 GB child, so not every minute

# --- normalisation -----------------------------------------------------------

_ARXIV_ID = re.compile(r"(\d{4}\.\d{4,5})(?:v\d+)?")
_TRACKING = {"ref", "source", "fbclid", "gclid"}
_TAGS = re.compile(r"<[^>]+>")
_VOTES = re.compile(r"Votes:\s*(\d+)")  # Tildes puts counts in the RSS description
_COMMENTS = re.compile(r"Comments:\s*(\d+)")
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


def is_http(url: str | None) -> bool:
    return bool(url) and urlsplit(url).scheme in ("http", "https")


def _keep_recent(items: list[FetchedItem], now: datetime) -> list[FetchedItem]:
    # Feed links end up in href, so anything but http(s) (javascript:, data:) is dropped.
    items = [i for i in items if is_http(i.url) and i.published_at >= now - MAX_AGE]
    items = [i if is_http(i.discussion_url) else replace(i, discussion_url=None) for i in items]
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
        raw_summary = entry.get("summary", "")
        summary = clean_text(raw_summary, 600)
        votes, comments = _VOTES.search(raw_summary), _COMMENTS.search(raw_summary)
        if summary.lower() == "comments" or summary.startswith("Link URL:"):  # link-aggregator boilerplate
            summary = ""
        title = clean_text(entry.get("title", ""), 300) or clean_text(summary, 100)
        if not title or title.startswith("[$]"):  # LWN marks subscriber-only articles this way
            continue
        published = _to_datetime(entry.get("published_parsed") or entry.get("updated_parsed")) or now
        items.append(FetchedItem(
            key=item_key(url),
            url=url,
            title=title,
            published_at=published,
            summary=summary,
            discussion_url=entry.get("comments"),
            score=int(votes.group(1)) if votes else None,
            comments=int(comments.group(1)) if comments else None,
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
            score=paper.get("upvotes"),
            comments=entry.get("numComments"),
        ))
    return _keep_recent(items, now)


def _iso_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def parse_hn_algolia(data: dict, now: datetime | None = None) -> list[FetchedItem]:
    now = now or datetime.now(UTC)
    items = []
    for hit in data.get("hits", []):
        if not hit.get("title"):
            continue
        thread = f"https://news.ycombinator.com/item?id={hit['objectID']}"
        url = hit.get("url") or thread  # Ask HN etc. have no external link
        items.append(FetchedItem(
            key=item_key(url),
            url=url,
            title=clean_text(hit["title"], 300),
            published_at=datetime.fromtimestamp(hit["created_at_i"], UTC),
            discussion_url=thread,
            score=hit.get("points"),
            comments=hit.get("num_comments"),
        ))
    return _keep_recent(items, now)


def parse_lobsters(data: list[dict], now: datetime | None = None) -> list[FetchedItem]:
    now = now or datetime.now(UTC)
    items = []
    for story in data:
        url = story.get("url") or story["comments_url"]
        items.append(FetchedItem(
            key=item_key(url),
            url=url,
            title=clean_text(story["title"], 300),
            published_at=_iso_datetime(story["created_at"]),
            summary=clean_text(story.get("description", ""), 600),
            discussion_url=story["comments_url"],
            score=story.get("score"),
            comments=story.get("comment_count"),
        ))
    return _keep_recent(items, now)


LW_QUERY = """{ posts(input: {terms: {view: "new", limit: 30, af: true}}) {
  results { title pageUrl url baseScore commentCount postedAt } } }"""


def parse_lw_graphql(data: dict, now: datetime | None = None) -> list[FetchedItem]:
    now = now or datetime.now(UTC)
    items = []
    for post in data.get("data", {}).get("posts", {}).get("results", []):
        url = post.get("url") or post["pageUrl"]  # link posts point elsewhere
        items.append(FetchedItem(
            key=item_key(url),
            url=url,
            title=clean_text(post["title"], 300),
            published_at=_iso_datetime(post["postedAt"]),
            discussion_url=post["pageUrl"],
            score=post.get("baseScore"),
            comments=post.get("commentCount"),
        ))
    return _keep_recent(items, now)


# --- fetching ----------------------------------------------------------------


async def fetch_source(client: httpx.AsyncClient, source: Source, store: Store) -> None:
    etag, last_modified = await asyncio.to_thread(store.cache_headers, source.id)
    headers = {}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified

    if source.fetcher == "lw_graphql":
        resp = await client.post(source.url, json={"query": LW_QUERY})
    else:
        resp = await client.get(source.url, headers=headers)
    # Parsing and SQLite writes are blocking; keep them off the event loop that serves pages.
    await asyncio.to_thread(save_response, store, source, resp, etag, last_modified)


def save_response(store: Store, source: Source, resp: httpx.Response, etag: str | None, last_modified: str | None) -> None:
    if resp.status_code == 304:
        store.save_fetch(source.id, None, etag, last_modified)
        return
    resp.raise_for_status()

    match source.fetcher:
        case "rss":
            items = parse_feed(resp.content, source)
        case "hf_papers":
            items = parse_hf_papers(resp.json())
        case "hn_algolia":
            items = parse_hn_algolia(resp.json())
        case "lobsters_json":
            items = parse_lobsters(resp.json())
        case "lw_graphql":
            items = parse_lw_graphql(resp.json())
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
                    await asyncio.to_thread(store.save_error, source.id, f"{type(exc).__name__}: {exc}")

    async with httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT},
        timeout=httpx.Timeout(15.0),
        follow_redirects=True,
    ) as client:
        await asyncio.gather(*(run_host(client, h, q) for h, q in by_host.items()))
    await asyncio.to_thread(store.prune)


class Refresher:
    """Background loop: every minute, fetch whichever selected sources are due."""

    def __init__(self, store: Store, catalogue: dict[str, Source]):
        self.store = store
        self.catalogue = catalogue
        self.wake = asyncio.Event()
        self.embed_failed_at = -EMBED_RETRY_SECONDS  # time.monotonic() of the last failed embed

    async def run(self) -> None:
        while True:
            try:
                selected = [self.catalogue[i] for i in settings.enabled_sources() if i in self.catalogue]
                if due := await asyncio.to_thread(self.store.due, selected):
                    await refresh(self.store, due)
                # Every cycle, not just after a fetch, so the backlog is embedded at startup.
                await self.embed()
            except Exception:
                log.exception("refresh cycle failed")
            try:
                await asyncio.wait_for(self.wake.wait(), TICK_SECONDS)
            except TimeoutError:
                pass
            self.wake.clear()

    async def embed(self) -> None:
        """Embed pending items in a child process; it logs to our stderr and takes the model's memory with it."""
        if time.monotonic() - self.embed_failed_at < EMBED_RETRY_SECONDS:
            return
        if not await asyncio.to_thread(pending, self.store):
            return
        child = await asyncio.create_subprocess_exec(sys.executable, "-m", "app.embed", cwd=ROOT)
        try:
            await asyncio.wait_for(child.wait(), EMBED_TIMEOUT_SECONDS)
            result = "ok" if child.returncode == 0 else f"failed (exit code {child.returncode})"
        except TimeoutError:
            result = f"timed out after {EMBED_TIMEOUT_SECONDS // 60} minutes"
        finally:
            if child.returncode is None:  # timed out, or the server is stopping
                child.kill()
        await asyncio.to_thread(self.store.save_embed_run, result)
        if result != "ok":
            log.warning("embedding %s; next try in %d minutes", result, EMBED_RETRY_SECONDS // 60)
            self.embed_failed_at = time.monotonic()
