from datetime import UTC, datetime, timedelta

from okaeri.fetch import PER_SOURCE_LIMIT, item_key, parse_feed, parse_hf_papers
from okaeri.sources import BY_ID

NOW = datetime(2026, 10, 11, 12, tzinfo=UTC)

HN_RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>Hacker News</title>
<link>https://news.ycombinator.com/</link>
<item><title>A &amp; B</title><link>https://example.com/post?utm_source=hn</link>
<pubDate>Sun, 11 Oct 2026 10:27:53 +0000</pubDate>
<comments>https://news.ycombinator.com/item?id=1</comments>
<description><![CDATA[<a href="https://news.ycombinator.com/item?id=1">Comments</a>]]></description></item>
<item><title>Relative</title><link>/item?id=2</link><pubDate>Sun, 11 Oct 2026 09:00:00 +0000</pubDate></item>
<item><title>Ancient</title><link>https://example.com/old</link><pubDate>Sun, 01 Jan 2023 09:00:00 +0000</pubDate></item>
</channel></rss>"""

ARXIV_ATOM = b"""<?xml version="1.0" encoding="UTF-8"?><feed xmlns="http://www.w3.org/2005/Atom">
<entry><id>http://arxiv.org/abs/2610.12467v1</id><title>CSF:   Contextual
  Safety</title><published>2026-10-08T17:59:50Z</published>
<link href="https://arxiv.org/abs/2610.12467v1" rel="alternate" type="text/html"/>
<summary>Text-conditioned <b>motion</b> generators.</summary></entry></feed>"""


def test_parse_rss():
    items = parse_feed(HN_RSS, BY_ID["hn"], now=NOW)
    assert [i.title for i in items] == ["A & B", "Relative"]  # old item dropped
    first, second = items
    assert first.key == "example.com/post"
    assert first.discussion_url == "https://news.ycombinator.com/item?id=1"
    assert first.summary == ""  # bare "Comments" link stripped
    assert first.published_at == datetime(2026, 10, 11, 10, 27, 53, tzinfo=UTC)
    assert second.url == "https://news.ycombinator.com/item?id=2"


def test_parse_atom_arxiv():
    [paper] = parse_feed(ARXIV_ATOM, BY_ID["arxiv-cs.lg"], now=NOW)
    assert paper.title == "CSF: Contextual Safety"
    assert paper.key == "arxiv:2610.12467"
    assert paper.summary == "Text-conditioned motion generators."


def test_parse_hf_papers():
    data = [{"title": "Lattice", "summary": "x", "publishedAt": "2026-10-07T20:00:00.000Z",
             "paper": {"id": "2610.11216"}}]
    [p] = parse_hf_papers(data, now=NOW)
    assert p.key == "arxiv:2610.11216"  # merges with the arXiv listing
    assert p.url == "https://huggingface.co/papers/2610.11216"


def test_per_source_limit():
    entries = "".join(
        f"<item><title>t{i}</title><link>https://e.com/{i}</link>"
        f"<pubDate>{(NOW - timedelta(minutes=i)).strftime('%a, %d %b %Y %H:%M:%S +0000')}</pubDate></item>"
        for i in range(PER_SOURCE_LIMIT + 10)
    )
    feed = f'<rss version="2.0"><channel><title>x</title>{entries}</channel></rss>'.encode()
    items = parse_feed(feed, BY_ID["hn"], now=NOW)
    assert len(items) == PER_SOURCE_LIMIT and items[0].title == "t0"


def test_item_key():
    assert item_key("https://www.Example.com/a/?utm_medium=x&b=2&a=1#frag") == "example.com/a?a=1&b=2"
    assert item_key("http://example.com/a") == item_key("https://example.com/a/")
    assert item_key("https://arxiv.org/pdf/2610.00001v3") == "arxiv:2610.00001"
