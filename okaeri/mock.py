"""Mock data standing in for fetched feeds until RSS ingestion exists."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

Kind = Literal["paper", "blog", "forum", "news"]
KINDS: tuple[Kind, ...] = ("paper", "blog", "forum", "news")


@dataclass(frozen=True)
class Article:
    id: str
    title: str
    url: str
    source: str
    kind: Kind
    published_at: datetime
    also_on: tuple[str, ...] = ()


@dataclass(frozen=True)
class Source:
    id: str
    name: str
    kind: Kind
    url: str


# (id, title, url, source, kind, age, also_on). Order is deliberately not chronological.
_RAW: list[tuple[str, str, str, str, Kind, timedelta, tuple[str, ...]]] = [
    ("a01", "Scaling laws for sparse mixture-of-experts at small compute budgets",
     "https://arxiv.org/abs/2410.00001", "arXiv", "paper", timedelta(hours=3), ("Hacker News",)),
    ("a02", "The quiet revolution in solid-state batteries",
     "https://www.quantamagazine.org/", "Quanta", "news", timedelta(hours=9), ()),
    ("a03", "Why I stopped using ORMs (again)",
     "https://example.com/orms", "Julia Evans", "blog", timedelta(minutes=40), ("Lobsters",)),
    ("a04", "Ask HN: What's your local-first stack in 2026?",
     "https://news.ycombinator.com/", "Hacker News", "forum", timedelta(hours=1, minutes=20), ()),
    ("a05", "Diffusion models as implicit physics simulators",
     "https://arxiv.org/abs/2410.00002", "arXiv", "paper", timedelta(days=1, hours=2), ()),
    ("a06", "A tour of the new Python JIT",
     "https://example.com/python-jit", "Simon Willison", "blog", timedelta(hours=5), ("Hacker News", "Lobsters")),
    ("a07", "Sizing a home server for embeddings",
     "https://lobste.rs/", "Lobsters", "forum", timedelta(hours=14), ()),
    ("a08", "Webb spots carbon-rich dust in the early universe",
     "https://www.nature.com/", "Nature News", "news", timedelta(days=2), ("Quanta",)),
    ("a09", "Retrieval heads: where long-context models actually look",
     "https://arxiv.org/abs/2410.00003", "arXiv", "paper", timedelta(days=3, hours=4), ()),
    ("a10", "Notes on building a calm homepage",
     "https://example.com/calm", "Robin Sloan", "blog", timedelta(days=4), ()),
    ("a11", "Postgres 19 release notes, annotated",
     "https://example.com/pg19", "Crunchy Data", "blog", timedelta(hours=22), ("Hacker News",)),
    ("a12", "Show HN: A 2kB RSS reader that runs in your terminal",
     "https://news.ycombinator.com/", "Hacker News", "forum", timedelta(days=1, hours=8), ()),
    ("a13", "Protein language models predict enzyme thermostability",
     "https://www.biorxiv.org/", "bioRxiv", "paper", timedelta(days=5), ()),
    ("a14", "EU finalises open-weights model guidance",
     "https://arstechnica.com/", "Ars Technica", "news", timedelta(hours=7), ("Hacker News",)),
    ("a15", "What the r/MachineLearning crowd thinks of test-time training",
     "https://www.reddit.com/r/MachineLearning/", "r/MachineLearning", "forum", timedelta(days=9), ()),
    ("a16", "Mechanistic interpretability of in-context learning in small transformers",
     "https://arxiv.org/abs/2410.00004", "arXiv", "paper", timedelta(hours=11), ()),
    ("a17", "Lessons from running SQLite in production for five years",
     "https://example.com/sqlite", "Ben Johnson", "blog", timedelta(hours=2, minutes=10), ("Hacker News",)),
    ("a18", "Ask Lobsters: How do you keep up with papers?",
     "https://lobste.rs/", "Lobsters", "forum", timedelta(hours=4), ()),
    ("a19", "Fusion startup reports record plasma confinement time",
     "https://arstechnica.com/", "Ars Technica", "news", timedelta(hours=16), ()),
    ("a20", "A minimal model of grokking via weight norm dynamics",
     "https://arxiv.org/abs/2410.00005", "arXiv", "paper", timedelta(days=1, hours=14), ()),
    ("a21", "The case for boring technology, revisited",
     "https://example.com/boring", "Dan McKinley", "blog", timedelta(days=2, hours=6), ("Lobsters",)),
    ("a22", "Show HN: Local embeddings for your RSS feeds",
     "https://news.ycombinator.com/", "Hacker News", "forum", timedelta(hours=6, minutes=30), ()),
    ("a23", "Mathematicians prove long-standing conjecture on sphere packing",
     "https://www.quantamagazine.org/", "Quanta", "news", timedelta(days=1, hours=5), ("Hacker News",)),
    ("a24", "Single-cell atlas of the developing human cortex",
     "https://www.biorxiv.org/", "bioRxiv", "paper", timedelta(days=2, hours=20), ()),
    ("a25", "Writing a tiny Lisp in a weekend",
     "https://example.com/lisp", "Julia Evans", "blog", timedelta(days=3), ()),
    ("a26", "Linux 7.2 merge window: what's new in io_uring",
     "https://lwn.net/", "LWN.net", "news", timedelta(hours=19), ("Lobsters",)),
    ("a27", "Discussion: is RLHF still necessary with better pretraining data?",
     "https://www.reddit.com/r/MachineLearning/", "r/MachineLearning", "forum", timedelta(days=2, hours=3), ()),
    ("a28", "Efficient attention via learned token merging",
     "https://arxiv.org/abs/2410.00006", "arXiv", "paper", timedelta(days=4, hours=7), ()),
    ("a29", "On keeping a lab notebook as a programmer",
     "https://example.com/notebook", "Simon Willison", "blog", timedelta(days=6), ()),
    ("a30", "New exoplanet survey finds water worlds are common",
     "https://www.nature.com/", "Nature News", "news", timedelta(days=5, hours=12), ()),
    ("a31", "Ask HN: Favourite calm, low-noise websites?",
     "https://news.ycombinator.com/", "Hacker News", "forum", timedelta(days=3, hours=9), ()),
    ("a32", "Benchmarking small language models on scientific QA",
     "https://arxiv.org/abs/2410.00007", "arXiv", "paper", timedelta(days=7), ("Hacker News",)),
    ("a33", "Postgres as a queue: a practical guide",
     "https://example.com/pg-queue", "Crunchy Data", "blog", timedelta(days=8), ()),
    ("a34", "Ocean heat content hits new high, study finds",
     "https://www.nature.com/", "Nature News", "news", timedelta(days=10), ()),
    ("a35", "Tildes thread: the best technical books you read this year",
     "https://tildes.net/~comp", "Tildes", "forum", timedelta(days=11), ()),
]


def articles() -> list[Article]:
    """Fresh article list; timestamps are relative to the moment of the call."""
    now = datetime.now(UTC)
    return [
        Article(id=i, title=t, url=u, source=s, kind=k, published_at=now - age, also_on=also)
        for i, t, u, s, k, age, also in _RAW
    ]


SOURCES: list[Source] = [
    Source("arxiv-cs-lg", "arXiv cs.LG", "paper", "https://arxiv.org/list/cs.LG/recent"),
    Source("arxiv-cs-cl", "arXiv cs.CL", "paper", "https://arxiv.org/list/cs.CL/recent"),
    Source("biorxiv", "bioRxiv", "paper", "https://www.biorxiv.org/"),
    Source("paperswithcode", "Papers with Code", "paper", "https://paperswithcode.com/"),
    Source("simonw", "Simon Willison", "blog", "https://simonwillison.net/"),
    Source("jvns", "Julia Evans", "blog", "https://jvns.ca/"),
    Source("robinsloan", "Robin Sloan", "blog", "https://www.robinsloan.com/"),
    Source("crunchy", "Crunchy Data", "blog", "https://www.crunchydata.com/blog"),
    Source("hn", "Hacker News", "forum", "https://news.ycombinator.com/"),
    Source("lobsters", "Lobsters", "forum", "https://lobste.rs/"),
    Source("r-ml", "r/MachineLearning", "forum", "https://www.reddit.com/r/MachineLearning/"),
    Source("tildes", "Tildes ~comp", "forum", "https://tildes.net/~comp"),
    Source("quanta", "Quanta", "news", "https://www.quantamagazine.org/"),
    Source("nature", "Nature News", "news", "https://www.nature.com/news"),
    Source("ars", "Ars Technica", "news", "https://arstechnica.com/"),
    Source("lwn", "LWN.net", "news", "https://lwn.net/"),
]
