"""Ranking seam. Every article list shown to the user goes through rank().

Latest is plain recency. Recommended adds up five signals, each scaled 0..1, with weights in Settings:
how close a story is to what you opened or liked, how fresh it is, how many points and comments it has,
a little chance, minus how close it is to what you hid. Onboarding learns the first four weights from
your ratings (learn()); after that the weights are yours to tune. Chance is never learned.
"""

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime

import numpy as np

from app.models import Article, Event
from app.sources import MEDIA, medium_of


@dataclass(frozen=True)
class Breakdown:
    """One story's Recommended score, taken apart so Settings can show it."""

    article: Article
    like: float
    hidden: float
    fresh: float
    popular: float
    random: float
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
    sig, nearest = signals(newest, [k for k in liked if k in vectors], [k for k in hidden if k in vectors], vectors)
    w = settings["ranking"]
    score = sum(w[name] * values for name, values in sig.items() if name != "hidden") - w["hidden"] * sig["hidden"]
    rows = [Breakdown(*row) for row in zip(newest, *sig.values(), nearest, score)]
    return sorted(rows, key=lambda b: b.score, reverse=True)  # stable: equal scores stay newest first


def signals(
    articles: list[Article], liked: list[str], hidden: list[str], vectors: dict[str, np.ndarray]
) -> tuple[dict[str, np.ndarray], list[str | None]]:
    """Every signal for every story, 0..1, in Breakdown's order; and the liked story each is nearest to."""
    like, nearest = closeness(articles, liked, vectors)
    dislike, _ = closeness(articles, hidden, vectors)
    sig = {"like": like, "hidden": dislike, "fresh": freshness(articles), "popular": popularity(articles), "random": chance(articles)}
    return sig, nearest


# Ratings before the learned weights count for half of what the ratings say: a few clicks steer, not swing.
HALF_TRUST_AT = 5


def learn(liked: list[Article], disliked: list[Article], vectors: dict[str, np.ndarray]) -> dict[str, float]:
    """Weights from onboarding ratings. Each starts at 0.5 and moves by how much more of its signal the stories
    you liked had than the ones you didn't (less of it, for hidden, which counts against).
    Liking only fresh stories, say, turns Fresh up. Chance is left out: clicks would always turn it down."""
    if not liked or not disliked:
        return {name: 0.5 for name in ("like", "hidden", "fresh", "popular")}
    rated = liked + disliked
    sig, _ = signals(rated, [], [], vectors)
    # A story isn't its own match, so a lone like (or dislike) has nothing to be like: wait for a second one.
    if len(liked) >= 2:
        sig["like"] = typical_closeness(rated, [a.key for a in liked if a.key in vectors], vectors)
    if len(disliked) >= 2:
        sig["hidden"] = typical_closeness(rated, [a.key for a in disliked if a.key in vectors], vectors)
    trust = len(rated) / (len(rated) + HALF_TRUST_AT)
    gap = {name: sig[name][: len(liked)].mean() - sig[name][len(liked) :].mean() for name in ("like", "hidden", "fresh", "popular")}
    gap["hidden"] = -gap["hidden"]
    return {name: float(np.clip(0.5 + g * trust, 0, 1)) for name, g in gap.items()}


def typical_closeness(articles: list[Article], keys: list[str], vectors: dict[str, np.ndarray]) -> np.ndarray:
    """Like closeness(), but the average over `keys` rather than the nearest, as a percentile. For learning:
    a story you rated down has one more liked story to be near than one you rated up, and the nearest of
    more stories is closer by chance; an average isn't."""
    out = np.zeros(len(articles))
    embedded = [i for i, a in enumerate(articles) if a.key in vectors]
    if len(keys) < 2 or not embedded:
        return out
    sims = np.array([vectors[articles[i].key] for i in embedded]) @ np.array([vectors[k] for k in keys]).T
    sims[np.array([[articles[i].key == k for k in keys] for i in embedded])] = np.nan  # not itself
    out[embedded] = percentile(np.nanmean(sims, axis=1))
    return out


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
    days = np.array([(now - a.published_at).total_seconds() / 86400 / MEDIA[medium_of(a)]["max_age_days"] for a in articles])
    return np.clip(1 - days, 0, 1)


def chance(articles: list[Article]) -> np.ndarray:
    """A roll of the dice per story, the same all day: so you don't get stuck in what you already like,
    and a reload doesn't reshuffle the page."""
    day = date.today().isoformat()
    rolls = [hashlib.blake2b(f"{day}:{a.key}".encode(), digest_size=8).digest() for a in articles]
    return np.array([int.from_bytes(r) / 2**64 for r in rolls])


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
