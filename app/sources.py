"""The curated source catalog and its tags, loaded from catalog/.

Each source has one medium: who writes it and how it's published, not what about. A research venue is a paper
(Nature's feed carries some news too: still paper), a person, lab or company writing on its own site is a blog
(newsletters too), a newsroom or magazine with editors is news, links ranked by a community are a forum.

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
# label, description and max_age_days (how long a story stays on the homepage: news goes stale fast, blogs post
# rarely). In order: when a story comes from several media, the first is shown and the others are "also on".
MEDIA: dict[str, dict] = _VOCAB["media"]
TOPICS: frozenset[str] = frozenset(_VOCAB["topics"])
TAG_DESCRIPTIONS: dict[str, str] = _VOCAB["topics"]
LANGUAGES: dict[str, str] = _VOCAB["languages"]  # code -> name


def known_tags(tags: Iterable[str], where: str) -> tuple[str, ...]:
    for tag in tags:
        if tag not in TOPICS:
            log.warning("%s: ignoring unknown tag %r", where, tag)
    return tuple(t for t in tags if t in TOPICS)


def known_media(media: Iterable[str], where: str) -> tuple[str, ...]:
    for medium in media:
        if medium not in MEDIA:
            log.warning("%s: ignoring unknown medium %r", where, medium)
    return tuple(m for m in media if m in MEDIA)


def _source(raw: dict) -> Source:
    tags = known_tags(raw["tags"], raw["id"])
    if raw["medium"] not in MEDIA:
        raise ValueError(f"source {raw['id']!r} has unknown medium {raw['medium']!r}")
    if raw["language"] not in LANGUAGES:
        raise ValueError(f"source {raw['id']!r} has unknown language {raw['language']!r}")
    return Source(**{**raw, "tags": tags})


SOURCES: list[Source] = [_source(s) for s in json.loads((ROOT / "catalog" / "sources.json").read_text())]
BY_ID: dict[str, Source] = {s.id: s for s in SOURCES}


def known_sources(ids: Iterable[str], where: str) -> tuple[str, ...]:
    for id in ids:
        if id not in BY_ID:
            log.warning("%s: ignoring unknown source %r", where, id)
    return tuple(id for id in ids if id in BY_ID)


# The seam for item-level tags (from embeddings) later; for now an article has its source's tags.
def tags_for(article: Article) -> frozenset[str]:
    return frozenset(BY_ID[article.source_id].tags)


def medium_of(article: Article) -> str:
    return BY_ID[article.source_id].medium


def speaks(source: Source, languages: Iterable[str]) -> bool:
    return source.language in languages


def source_matches(source: Source, media: Iterable[str], topics: Iterable[str]) -> bool:
    """For onboarding. General sources (no topic) fit any topic."""
    if source.medium not in media:
        return False
    return not source.tags or bool(set(source.tags) & set(topics))


def tab_covers(source: Source, tab: dict) -> bool:
    """Each part of a tab narrows the one before: its media, then its topics within those, then just its picked
    sources. A part with nothing picked doesn't narrow."""
    media, topics, picked = tab.get("media", ()), set(tab.get("topics", ())), tab.get("sources", ())
    return (
        (not media or source.medium in media)
        and (not topics or bool(topics & set(source.tags)))
        and (not picked or source.id in picked)
    )


def in_tab(article: Article, tab: dict) -> bool:
    """In the tab if any source the story came from is one the tab covers."""
    return any(tab_covers(BY_ID[s], tab) for s in article.source_ids)
