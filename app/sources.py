"""The curated source catalog and its tags, loaded from catalog/.

arXiv entries use the API because the arXiv RSS feeds are empty on weekends.
Reddit refreshes slowly because it rate-limits (429) quickly.
"""

import json
import logging
from collections.abc import Iterable

from app import ROOT
from app.models import Article, Source

log = logging.getLogger("okaeri")

_VOCAB = json.loads((ROOT / "catalog" / "tags.json").read_text())
FORMATS: frozenset[str] = frozenset(_VOCAB["formats"])
TOPICS: frozenset[str] = frozenset(_VOCAB["topics"])


def known_tags(tags: Iterable[str], where: str) -> tuple[str, ...]:
    for tag in tags:
        if tag not in FORMATS | TOPICS:
            log.warning("%s: ignoring unknown tag %r", where, tag)
    return tuple(t for t in tags if t in FORMATS | TOPICS)


def _source(raw: dict) -> Source:
    tags = known_tags(raw["tags"], raw["id"])
    formats = [t for t in tags if t in FORMATS]
    if len(formats) != 1:
        raise ValueError(f"source {raw['id']!r} needs exactly one format tag, has {formats}")
    return Source(**{**raw, "tags": tags})


SOURCES: list[Source] = [_source(s) for s in json.loads((ROOT / "catalog" / "sources.json").read_text())]
BY_ID: dict[str, Source] = {s.id: s for s in SOURCES}


def known_sources(ids: Iterable[str], where: str) -> tuple[str, ...]:
    for id in ids:
        if id not in BY_ID:
            log.warning("%s: ignoring unknown source %r", where, id)
    return tuple(id for id in ids if id in BY_ID)


def source_format(source: Source) -> str:
    return next(t for t in source.tags if t in FORMATS)


# The seam for item-level tags (from embeddings) later; for now an article has its source's tags.
def tags_for(article: Article) -> frozenset[str]:
    return frozenset(BY_ID[article.source_id].tags)


def format_of(article: Article) -> str:
    return source_format(BY_ID[article.source_id])


def source_matches(source: Source, formats: Iterable[str], topics: Iterable[str]) -> bool:
    """For onboarding. Picking nothing means everything; general sources (no topic) fit any topic."""
    formats, topics, own_topics = set(formats), set(topics), set(source.tags) & TOPICS
    if formats and source_format(source) not in formats:
        return False
    return not topics or not own_topics or bool(own_topics & topics)


def tab_covers(source: Source, tab_tags: Iterable[str], tab_sources: Iterable[str]) -> bool:
    """Each part narrows the one before: its formats, then its topics within those, then just its picked sources.
    A part with nothing picked doesn't narrow."""
    formats, topics, picked = set(tab_tags) & FORMATS, set(tab_tags) & TOPICS, set(tab_sources)
    return (
        (not formats or source_format(source) in formats)
        and (not topics or bool(topics & set(source.tags)))
        and (not picked or source.id in picked)
    )


def in_tab(article: Article, tab_tags: Iterable[str], tab_sources: Iterable[str]) -> bool:
    """In the tab if any source the story came from is one the tab covers."""
    return any(tab_covers(BY_ID[s], tab_tags, tab_sources) for s in article.source_ids)
