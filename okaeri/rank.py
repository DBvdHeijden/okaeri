"""Ranking seam. Every article list shown to the user goes through rank().

For now this is plain recency; the local-embedder ranking replaces it later.
"""

from collections.abc import Sequence

from okaeri.models import Article


def rank(articles: Sequence[Article]) -> list[Article]:
    return sorted(articles, key=lambda a: a.published_at, reverse=True)
