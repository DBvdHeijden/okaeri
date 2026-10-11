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


def source_format(source: Source) -> str:
    return next(t for t in source.tags if t in FORMATS)


# The seam for item-level tags (from embeddings) later; for now an article has its source's tags.
def tags_for(article: Article) -> frozenset[str]:
    return frozenset(BY_ID[article.source_id].tags)


def format_of(article: Article) -> str:
    return source_format(BY_ID[article.source_id])


def in_tab(article: Article, tab_tags: Iterable[str]) -> bool:
    """Any tag within a group (formats, topics) matches; every group the tab uses must match."""
    have, wanted = tags_for(article), set(tab_tags)
    return all(have & group for group in (wanted & FORMATS, wanted & TOPICS) if group)
