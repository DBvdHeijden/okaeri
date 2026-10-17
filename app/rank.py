"""Ranking seam. Every article list shown to the user goes through rank().

Latest is plain recency. Recommended scores a story from five signals, each scaled 0..1, with weights in Settings:
what you'd like (how close it is to what you opened or liked, plus its points and comments, plus a little chance),
times what you wouldn't (how close it is to what you hid), times how fresh it is. Multiplying keeps time in play
for every story: an old one has to be much more relevant than a new one to beat it. Onboarding learns the like,
hidden, fresh and popular weights from your ratings (learn()); after that the weights are yours to tune.
Chance is never learned. docs/ranking.md walks through it.

Closeness is a taste per topic: a story is compared with what you liked (or hid) in its own topics, and placed
among the other stories in them. Liking AI lifts AI stories without sinking politics, and a topic you haven't
rated yet stays neutral.
"""

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime

import numpy as np

from app.models import Article, Event
from app.sources import MEDIA, medium_of, tags_for


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
    topics: dict[str, frozenset[str]] | None = None,
) -> list[Article]:
    """`topics`: of the stories you opened, liked or hid that may have left `articles` (store.stories() has them)."""
    if sort == "recommended":
        return [b.article for b in explain(articles, events, settings, vectors or {}, topics or {})]
    hidden = switched_on(events, "hide", "unhide")
    return sorted((a for a in articles if a.key not in hidden), key=lambda a: a.published_at, reverse=True)


def explain(
    articles: Sequence[Article], events: Sequence[Event], settings: dict, vectors: dict[str, np.ndarray],
    topics: dict[str, frozenset[str]],
) -> list[Breakdown]:
    """Recommended, best first, with every score taken apart."""
    newest = rank(articles, events, settings)
    liked = {e.key for e in events if e.type == "click"} | switched_on(events, "seed", "unseed").keys()
    hidden = switched_on(events, "hide", "unhide")
    topics = topics | {a.key: tags_for(a) for a in articles}
    sig, nearest = signals(newest, [k for k in liked if k in vectors], [k for k in hidden if k in vectors], vectors, topics)
    w = settings["ranking"]
    wanted = w["like"] * sig["like"] + w["popular"] * sig["popular"] + CHANCE * w["random"] * sig["random"]
    # Fresh 0.5 fades a story by half every half-life of its medium; 1 twice as fast, 0 not at all.
    score = wanted * (1 - w["hidden"] * sig["hidden"]) * sig["fresh"] ** (2 * w["fresh"])
    rows = [Breakdown(*row) for row in zip(newest, *sig.values(), nearest, score)]
    return sorted(rows, key=lambda b: b.score, reverse=True)  # stable: equal scores stay newest first


def signals(
    articles: list[Article], liked: list[str], hidden: list[str], vectors: dict[str, np.ndarray],
    topics: dict[str, frozenset[str]],
) -> tuple[dict[str, np.ndarray], list[str | None]]:
    """Every signal for every story, 0..1, in Breakdown's order; and the liked story each is nearest to.
    `topics` has the topics of the liked and hidden stories."""
    like, nearest = closeness(articles, liked, vectors, topics)
    dislike, _ = closeness(articles, hidden, vectors, topics)
    sig = {"like": like, "hidden": dislike, "fresh": freshness(articles), "popular": popularity(articles), "random": chance(articles)}
    return sig, nearest


# Chance only breaks near-ties: at full Surprise it counts a fifth of what a full Like does. Spread over 0..1
# like the other signals, it used to decide much of the top of the page by itself.
CHANCE = 0.2

# Ratings before the learned weights count for half of what the ratings say: a few clicks steer, not swing.
HALF_TRUST_AT = 5


def learn(liked: list[Article], disliked: list[Article], vectors: dict[str, np.ndarray]) -> dict[str, float]:
    """Weights from onboarding ratings. Each starts at 0.5 and moves by how much more of its signal the stories
    you liked had than the ones you didn't (less of it, for hidden, which counts against).
    Liking only fresh stories, say, turns Fresh up. Chance is left out: clicks would always turn it down."""
    if not liked or not disliked:
        return {name: 0.5 for name in ("like", "hidden", "fresh", "popular")}
    rated = liked + disliked
    sig, _ = signals(rated, [], [], vectors, {})
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


def closeness(
    articles: list[Article], keys: list[str], vectors: dict[str, np.ndarray], topics: dict[str, frozenset[str]]
) -> tuple[np.ndarray, list[str | None]]:
    """How close each story is to the nearest of `keys` in its own topics, as a percentile among the stories in
    those topics, and which key that is. Per topic, so one you rated a lot doesn't crowd out the rest; one with no
    keys yet is a neutral 0.5. A story in two topics gets the mean. Keys and stories without topics (Hacker News,
    Lobsters) count everywhere. Raw cosine similarities sit in a narrow band; percentiles make them weigh like the
    other signals."""
    out, nearest = np.zeros(len(articles)), [None] * len(articles)
    embedded = [i for i, a in enumerate(articles) if a.key in vectors]
    if not keys or not embedded:
        return out, nearest
    own = {key: j for j, key in enumerate(keys)}
    sims = np.array([vectors[articles[i].key] for i in embedded]) @ np.array([vectors[k] for k in keys]).T
    for row, i in enumerate(embedded):
        if articles[i].key in own:
            sims[row, own[articles[i].key]] = -1  # a story you opened isn't its own best match
    story_topics = [tags_for(articles[i]) for i in embedded]
    key_topics = [topics.get(k, frozenset()) for k in keys]
    total, parts = np.zeros(len(embedded)), np.zeros(len(embedded))
    best = np.full(len(embedded), -np.inf)
    for topic in {t for ts in story_topics for t in ts} | {None}:  # None: the stories without topics
        rows = [r for r, ts in enumerate(story_topics) if (topic in ts if topic else not ts)]
        cols = [j for j, ts in enumerate(key_topics) if not topic or not ts or topic in ts]
        if not rows:
            continue
        parts[rows] += 1
        if not cols:
            total[rows] += 0.5
            continue
        within = sims[np.ix_(rows, cols)]
        total[rows] += percentile(within.max(axis=1))
        for r, j, sim in zip(rows, within.argmax(axis=1), within.max(axis=1)):
            if sim > best[r]:
                best[r], nearest[embedded[r]] = sim, keys[cols[j]]
    out[embedded] = total / parts
    return out, nearest


def freshness(articles: list[Article]) -> np.ndarray:
    """1 when just published, halving every half-life of the story's medium: news fades faster than blogs.
    By real age rather than as a share of the time on the homepage, which kept a two-week-old blog post fresh."""
    now = datetime.now(UTC)
    half_lives = np.array([(now - a.published_at).total_seconds() / 86400 / MEDIA[medium_of(a)]["half_life_days"] for a in articles])
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
