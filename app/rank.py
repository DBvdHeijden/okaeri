"""Ranking seam. Every article list shown to the user goes through rank().

For now this is plain recency; the local-embedder ranking replaces it later.
"""

from collections.abc import Sequence

from app.models import Article, Event


def rank(articles: Sequence[Article], events: Sequence[Event], settings: dict) -> list[Article]:
    latest = {e.key: e.type for e in events}  # events come oldest first
    visible = [a for a in articles if latest.get(a.key) != "hide"]
    return sorted(visible, key=lambda a: a.published_at, reverse=True)


def sample(articles: Sequence[Article], size: int) -> list[Article]:
    """A spread for onboarding: the best story from each source in turn, so no one source fills it."""
    by_source: dict[str, list[Article]] = {}
    for a in articles:
        by_source.setdefault(a.source_id, []).append(a)
    picked = []
    while len(picked) < size and any(by_source.values()):
        picked += [queue.pop(0) for queue in by_source.values() if queue]
    return picked[:size]
