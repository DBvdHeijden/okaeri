from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

# "rss" covers RSS and Atom (feedparser handles both); the rest are JSON APIs
# used where the RSS feed lacks points and comment counts.
Fetcher = Literal["rss", "hf_papers", "hn_algolia", "lobsters_json", "lw_graphql"]


@dataclass(frozen=True)
class Source:
    id: str
    name: str
    medium: str  # paper, blog, news or forum: see app.sources
    tags: tuple[str, ...]  # 0-2 topics
    url: str  # what we fetch
    site: str  # what we show
    language: str  # ISO 639-1 code of the feed's language, e.g. "en", "nl"
    description: str = ""
    fetcher: Fetcher = "rss"
    refresh_minutes: int = 30  # blogs; forums and news override, papers go slower


@dataclass(frozen=True)
class FetchedItem:
    """One entry as parsed from a feed, before storage."""

    key: str  # normalised URL; items with the same key are the same story
    url: str
    title: str
    published_at: datetime
    summary: str = ""
    discussion_url: str | None = None
    score: int | None = None  # points / upvotes, where the source has them
    comments: int | None = None


@dataclass(frozen=True)
class Event:
    type: Literal["seed", "unseed", "click", "hide", "unhide"]
    key: str
    at: datetime


@dataclass(frozen=True)
class Article:
    """One story as shown on the homepage, merged across sources."""

    id: str
    title: str
    url: str
    source: str
    source_id: str  # the source shown; source_ids has every source the story came from
    published_at: datetime  # for History: when it was opened
    also_on: tuple[str, ...] = ()
    key: str = ""
    discussion_url: str | None = None
    score: int | None = None
    comments: int | None = None
    summary: str = field(default="", repr=False)
    source_ids: tuple[str, ...] = ()
