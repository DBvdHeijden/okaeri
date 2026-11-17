"""Ranking seam. Every article list shown to the user goes through rank().

Latest is plain recency. Recommended scores a story from five signals, each scaled 0..1, with weights in Settings:
what you'd like (how the stories most like it went: opened or liked, or hidden; and how stories from its source
went), plus its points and comments, plus a little chance, times how fresh it is. Multiplying keeps time in play
for every story: an old one has to be more relevant than a new one to beat it. Onboarding learns the like,
hidden, fresh and popular weights from your ratings (learn()); after that the weights are yours to tune.
Chance is never learned. docs/ranking.md walks through it, and how we measured it.
"""

import hashlib
from collections import Counter
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
    source: float
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
    rated: dict[str, Article] | None = None,
) -> list[Article]:
    """`rated`: the stories you opened, liked or hid, which may have left `articles` (store.stories() has them)."""
    if sort == "recommended":
        return [b.article for b in explain(articles, events, settings, vectors or {}, rated or {})]
    hidden = switched_on(events, "hide", "unhide")
    return sorted((a for a in articles if a.key not in hidden), key=lambda a: a.published_at, reverse=True)


def explain(
    articles: Sequence[Article],
    events: Sequence[Event],
    settings: dict,
    vectors: dict[str, np.ndarray],
    rated: dict[str, Article],
) -> list[Breakdown]:
    """Recommended, best first, with every score taken apart."""
    newest = rank(articles, events, settings)
    liked = {e.key for e in events if e.type == "click"} | switched_on(events, "seed", "unseed").keys()
    hidden = switched_on(events, "hide", "unhide").keys()
    w = settings["ranking"]
    sig, nearest = signals(newest, list(liked), list(hidden), vectors, rated | {a.key: a for a in articles}, w)
    like = (1 - SOURCE) * sig["like"] + SOURCE * sig["source"]
    wanted = w["like"] * like + w["popular"] * sig["popular"] + CHANCE * w["random"] * sig["random"]
    # Fresh 0.5 fades a story by half every half-life of its medium; 1 twice as fast, 0 not at all.
    score = wanted * sig["fresh"] ** (2 * w["fresh"])
    rows = [Breakdown(*row) for row in zip(newest, *sig.values(), nearest, score)]
    return sorted(rows, key=lambda b: b.score, reverse=True)  # stable: equal scores stay newest first


def signals(
    articles: list[Article],
    liked: list[str],
    hidden: list[str],
    vectors: dict[str, np.ndarray],
    rated: dict[str, Article],
    weights: dict[str, float],
) -> tuple[dict[str, np.ndarray], list[str | None]]:
    """Every signal for every story, 0..1, in Breakdown's order; and the liked story each is nearest to."""
    like, nearest = vote(
        articles, [k for k in liked if k in vectors], [k for k in hidden if k in vectors], vectors, weights["hidden"]
    )
    sig = {
        "like": like,
        "source": affinity(articles, [rated[k] for k in liked if k in rated], [rated[k] for k in hidden if k in rated]),
        "fresh": freshness(articles),
        "popular": popularity(articles),
        "random": chance(articles),
    }
    return sig, nearest


# Chance only breaks near-ties: at full Surprise it counts a fifth of what a full Like does. Spread over 0..1
# like the other signals, it used to decide much of the top of the page by itself.
CHANCE = 0.2

# How much of Like is how stories from the same source went, rather than the stories most like it. Some tastes
# are about form (essays, papers) more than topic, and embeddings mostly see topic.
SOURCE = 0.25

# The rated stories that vote on each story. Few enough that they're about the same thing.
NEIGHBOURS = 5

# Ratings before the learned weights count for half of what the ratings say: a few clicks steer, not swing.
HALF_TRUST_AT = 5


def learn(
    liked: list[Article], disliked: list[Article], vectors: dict[str, np.ndarray], pool: Sequence[Article]
) -> dict[str, float]:
    """Weights from onboarding ratings. Each starts at 0.5 and moves by how much more of its signal the stories
    you liked had than the ones you didn't (less of it, for hidden, which counts against).
    Liking only fresh stories, say, turns Fresh up. Chance is left out: clicks would always turn it down.
    Popularity is placed among all of `pool`: onboarding shows one story per source, alone in its source."""
    if not liked or not disliked:
        return {name: 0.5 for name in ("like", "hidden", "fresh", "popular")}
    rated = liked + disliked
    others = [a for a in pool if a.key not in {r.key for r in rated}]
    # A story isn't its own match, so a lone like (or dislike) has nothing to be like: wait for a second one.
    sig = {
        "like": typical_closeness(rated, [a.key for a in liked if a.key in vectors], vectors),
        "hidden": typical_closeness(rated, [a.key for a in disliked if a.key in vectors], vectors),
        "fresh": freshness(rated),
        "popular": popularity(rated + others)[: len(rated)],
    }
    trust = len(rated) / (len(rated) + HALF_TRUST_AT)
    gap = {name: s[: len(liked)].mean() - s[len(liked) :].mean() for name, s in sig.items()}
    gap["hidden"] = -gap["hidden"]
    return {name: float(np.clip(0.5 + g * trust, 0, 1)) for name, g in gap.items()}


def typical_closeness(articles: list[Article], keys: list[str], vectors: dict[str, np.ndarray]) -> np.ndarray:
    """How close each story is to `keys` on average, as a percentile. For learning: a story you rated down has one
    more liked story to be near than one you rated up, and the nearest of more stories is closer by chance; an
    average isn't."""
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


def vote(
    articles: list[Article], liked: list[str], hidden: list[str], vectors: dict[str, np.ndarray], hide_weight: float
) -> tuple[np.ndarray, list[str | None]]:
    """Of the NEIGHBOURS rated stories most like each story, the share you liked rather than hid, and the liked one
    it's nearest to. At Unlike 0.5 a hide counts as much as a like; 1 twice as much, 0 not at all. With nothing
    rated near it, or no vector yet, a story is a neutral 0.5. A vote rather than the nearest like: once you've
    liked a few papers every paper is near one, but not every paper's neighbours are ones you liked."""
    out, nearest = np.full(len(articles), 0.5), [None] * len(articles)
    keys = liked + hidden
    embedded = [i for i, a in enumerate(articles) if a.key in vectors]
    if not keys or not embedded:
        return out, nearest
    sims = np.array([vectors[articles[i].key] for i in embedded]) @ np.array([vectors[k] for k in keys]).T
    sims[np.array([[articles[i].key == k for k in keys] for i in embedded])] = -np.inf  # not itself
    is_liked = np.arange(len(keys)) < len(liked)
    top = np.argsort(-sims, axis=1)[:, :NEIGHBOURS]
    counted = np.take_along_axis(sims, top, axis=1) > -np.inf
    ups = (is_liked[top] & counted).sum(axis=1)
    downs = (~is_liked[top] & counted).sum(axis=1)
    out[embedded] = (ups + 1) / (ups + 2 * hide_weight * downs + 2)
    if liked:
        for row, j in enumerate(np.where(is_liked, sims, -np.inf).argmax(axis=1)):
            nearest[embedded[row]] = keys[j] if sims[row, j] > -np.inf else None
    return out, nearest


def affinity(articles: list[Article], liked: list[Article], hidden: list[Article]) -> np.ndarray:
    """How often you liked rather than hid stories from each story's source, leaning on how its medium went while
    the source has few ratings, and on a neutral 0.5 while the medium has few too."""
    prior = 3  # ratings before the source counts as much as its medium
    ups, downs = Counter(a.source_id for a in liked), Counter(a.source_id for a in hidden)
    medium_ups, medium_downs = Counter(map(medium_of, liked)), Counter(map(medium_of, hidden))
    out = []
    for a in articles:
        m = medium_of(a)
        medium = (medium_ups[m] + prior * 0.5) / (medium_ups[m] + medium_downs[m] + prior)
        out.append((ups[a.source_id] + prior * medium) / (ups[a.source_id] + downs[a.source_id] + prior))
    return np.array(out)


def freshness(articles: list[Article]) -> np.ndarray:
    """1 when just published, halving every half-life of the story's medium: news fades faster than blogs.
    By real age rather than as a share of the time on the homepage, which kept a two-week-old blog post fresh."""
    now = datetime.now(UTC)
    half_lives = np.array(
        [(now - a.published_at).total_seconds() / 86400 / MEDIA[medium_of(a)]["half_life_days"] for a in articles]
    )
    return 0.5 ** np.clip(half_lives, 0, None)


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
        out[idx] = percentile(
            np.array([np.log1p(articles[i].score or 0) + np.log1p(articles[i].comments or 0) for i in idx])
        )
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
