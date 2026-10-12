"""Ranking seam. Every article list shown to the user goes through rank().

Latest is plain recency. Recommended adds up four signals, each scaled 0..1, with weights you set in Settings:
how close a story is to what you opened or liked, how fresh it is, how many points and comments it has,
minus how close it is to what you hid. Your taste is learned from those events; the weights stay yours.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np

from app.models import MAX_AGE_DAYS, Article, Event
from app.sources import format_of


@dataclass(frozen=True)
class Breakdown:
    """One story's Recommended score, taken apart so Settings can show it."""

    article: Article
    like: float
    hidden: float
    fresh: float
    popular: float
    nearest: str | None  # the key of the opened or liked story it's most like
    score: float


def switched_on(events: Sequence[Event], on: str, off: str) -> dict[str, datetime]:
    """Stories whose latest on/off event is `on` (liked: seed/unseed, hidden: hide/unhide), with when."""
    state = {}
    for e in events:  # events come oldest first
        if e.type == on:
            state[e.key] = e.at
        elif e.type == off:
            state.pop(e.key, None)
    return state


def rank(
    articles: Sequence[Article],
    events: Sequence[Event],
    settings: dict,
    vectors: dict[str, np.ndarray] | None = None,
    sort: str = "latest",
) -> list[Article]:
    if sort == "recommended":
        return [b.article for b in explain(articles, events, settings, vectors or {})]
    hidden = switched_on(events, "hide", "unhide")
    return sorted((a for a in articles if a.key not in hidden), key=lambda a: a.published_at, reverse=True)


def explain(articles: Sequence[Article], events: Sequence[Event], settings: dict, vectors: dict[str, np.ndarray]) -> list[Breakdown]:
    """Recommended, best first, with every score taken apart."""
    newest = rank(articles, events, settings)
    liked = {e.key for e in events if e.type == "click"} | switched_on(events, "seed", "unseed").keys()
    hidden = switched_on(events, "hide", "unhide")
    w = settings["ranking"]
    like, nearest = closeness(newest, [k for k in liked if k in vectors], vectors)
    dislike, _ = closeness(newest, [k for k in hidden if k in vectors], vectors)
    fresh = freshness(newest)
    popular = popularity(newest)
    score = w["like"] * like - w["hidden"] * dislike + w["fresh"] * fresh + w["popular"] * popular
    rows = [Breakdown(*row) for row in zip(newest, like, dislike, fresh, popular, nearest, score)]
    return sorted(rows, key=lambda b: b.score, reverse=True)  # stable: equal scores stay newest first


def percentile(values: np.ndarray) -> np.ndarray:
    """Each value's place among the others, 0 (lowest) to 1 (highest); ties share the middle of their places."""
    if len(values) < 2:
        return np.full(len(values), 0.5)
    ordered = np.sort(values)
    places = np.searchsorted(ordered, values, "left") + np.searchsorted(ordered, values, "right") - 1
    return places / 2 / (len(values) - 1)


def closeness(articles: list[Article], keys: list[str], vectors: dict[str, np.ndarray]) -> tuple[np.ndarray, list[str | None]]:
    """How close each story is to the nearest of `keys`, as a percentile, and which one that is.
    Raw cosine similarities sit in a narrow band; percentiles make them weigh like the other signals."""
    out, nearest = np.zeros(len(articles)), [None] * len(articles)
    embedded = [i for i, a in enumerate(articles) if a.key in vectors]
    if not keys or not embedded:
        return out, nearest
    own = {key: j for j, key in enumerate(keys)}
    sims = np.array([vectors[articles[i].key] for i in embedded]) @ np.array([vectors[k] for k in keys]).T
    for row, i in enumerate(embedded):
        if articles[i].key in own:
            sims[row, own[articles[i].key]] = -1  # a story you opened isn't its own best match
        nearest[i] = keys[sims[row].argmax()]
    out[embedded] = percentile(sims.max(axis=1))
    return out, nearest


def freshness(articles: list[Article]) -> np.ndarray:
    """1 when just published, 0 when the story is about to leave the homepage; news fades faster than blogs."""
    now = datetime.now(UTC)
    days = np.array([(now - a.published_at).total_seconds() / 86400 / MAX_AGE_DAYS[format_of(a)] for a in articles])
    return np.clip(1 - days, 0, 1)


def popularity(articles: list[Article]) -> np.ndarray:
    """Points and comments as a percentile within the story's own source, since 300 points on Hacker News
    and 30 on Lobsters mean about the same. Stories without counts stay neutral at 0.5."""
    out = np.full(len(articles), 0.5)
    by_source: dict[str, list[int]] = {}
    for i, a in enumerate(articles):
        if a.score is not None or a.comments is not None:
            by_source.setdefault(a.source_id, []).append(i)
    for idx in by_source.values():
        out[idx] = percentile(np.array([np.log1p(articles[i].score or 0) + np.log1p(articles[i].comments or 0) for i in idx]))
    return out


def sample(articles: Sequence[Article], size: int) -> list[Article]:
    """A spread for onboarding: the first story from each source in turn, so no one source fills it."""
    by_source: dict[str, list[Article]] = {}
    for a in articles:
        by_source.setdefault(a.source_id, []).append(a)
    picked = []
    while len(picked) < size and any(by_source.values()):
        picked += [queue.pop(0) for queue in by_source.values() if queue]
    return picked[:size]
