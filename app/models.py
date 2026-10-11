from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

Kind = Literal["paper", "blog", "forum", "scitech", "news"]
KINDS: tuple[Kind, ...] = ("paper", "blog", "forum", "scitech", "news")
KIND_LABELS: dict[Kind, str] = {
    "paper": "Papers", "blog": "Blogs", "forum": "Forums", "scitech": "Sci & Tech", "news": "News",
}
# How long a story stays on the homepage. World news goes stale fast; blogs post rarely.
MAX_AGE_DAYS: dict[Kind, int] = {"paper": 14, "blog": 60, "forum": 7, "scitech": 14, "news": 3}

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
    type: Literal["seed", "click", "hide", "unhide"]
    key: str
    at: datetime


@dataclass(frozen=True)
class Article:
    """One story as shown on the homepage, merged across sources."""

    id: str
    title: str
    url: str
    source: str
    kind: Kind
    published_at: datetime  # for History: when it was opened
    also_on: tuple[str, ...] = ()
    key: str = ""
    discussion_url: str | None = None
    score: int | None = None
    comments: int | None = None
    summary: str = field(default="", repr=False)
