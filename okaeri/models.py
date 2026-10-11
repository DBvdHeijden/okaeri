from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

Kind = Literal["paper", "blog", "forum", "news"]
KINDS: tuple[Kind, ...] = ("paper", "blog", "forum", "news")

# "rss" covers RSS and Atom (feedparser handles both); the rest are JSON APIs
# used where the RSS feed lacks points and comment counts.
Fetcher = Literal["rss", "hf_papers", "hn_algolia", "lobsters_json", "lw_graphql"]


@dataclass(frozen=True)
class Source:
    id: str
    name: str
    kind: Kind
    url: str  # what we fetch
    site: str  # what we show
    description: str = ""
    fetcher: Fetcher = "rss"
    refresh_minutes: int = 60


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
class Article:
    """One story as shown on the homepage, merged across sources."""

    id: str
    title: str
    url: str
    source: str
    kind: Kind
    published_at: datetime
    also_on: tuple[str, ...] = ()
    discussion_url: str | None = None
    score: int | None = None
    comments: int | None = None
    summary: str = field(default="", repr=False)
