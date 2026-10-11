"""Ranking seam. Every article list shown to the user goes through rank().

Latest is plain recency. Recommended scores each story by its embedding: how close it is to the nearest
story you opened or liked, minus (half as strongly) how close it is to the nearest story you hid.
"""

from collections.abc import Sequence
from datetime import datetime

import numpy as np

from app.models import Article, Event

# A hidden story pushes its look-alikes down half as hard as a liked one pulls them up:
# one hide shouldn't bury a whole topic.
HIDDEN_WEIGHT = 0.5


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
    hidden = switched_on(events, "hide", "unhide")
    newest = sorted((a for a in articles if a.key not in hidden), key=lambda a: a.published_at, reverse=True)
    liked = {e.key for e in events if e.type == "click"} | switched_on(events, "seed", "unseed").keys()
    if sort != "recommended" or not vectors:
        return newest
    return recommended(newest, [k for k in liked if k in vectors], [k for k in hidden if k in vectors], vectors)


def recommended(newest: list[Article], liked: list[str], hidden: list[str], vectors: dict[str, np.ndarray]) -> list[Article]:
    if not liked:
        return newest  # nothing to go on yet
    likes, dislikes = np.array([vectors[k] for k in liked]), np.array([vectors[k] for k in hidden])
    own = {key: i for i, key in enumerate(liked)}

    def score(a: Article) -> float:
        if a.key not in vectors:
            return -np.inf  # not embedded yet: after the rest, newest first
        sims = likes @ vectors[a.key]
        if a.key in own:
            sims[own[a.key]] = -1  # a story you opened isn't its own best match
        return sims.max() - (HIDDEN_WEIGHT * (dislikes @ vectors[a.key]).max() if len(dislikes) else 0)

    return sorted(newest, key=score, reverse=True)  # stable: equal scores stay newest first


def sample(articles: Sequence[Article], size: int) -> list[Article]:
    """A spread for onboarding: the first story from each source in turn, so no one source fills it."""
    by_source: dict[str, list[Article]] = {}
    for a in articles:
        by_source.setdefault(a.source_id, []).append(a)
    picked = []
    while len(picked) < size and any(by_source.values()):
        picked += [queue.pop(0) for queue in by_source.values() if queue]
    return picked[:size]
