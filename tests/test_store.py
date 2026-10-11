from datetime import UTC, datetime, timedelta

from okaeri.sources import BY_ID
from tests.conftest import item


def test_merge_prefers_non_forum_source(store):
    store.save_fetch("hn", [item("https://jvns.ca/x", "HN title", discussion_url="https://hn/1")], None, None)
    store.save_fetch("jvns", [item("https://jvns.ca/x/", "Real title", hours_ago=3)], None, None)
    [a] = store.articles({i: BY_ID[i] for i in ("hn", "jvns")})
    assert (a.title, a.source, a.also_on, a.discussion_url) == ("Real title", "Julia Evans", ("Hacker News",), "https://hn/1")


def test_old_items_hidden(store):
    store.save_fetch("jvns", [item("https://jvns.ca/old", hours_ago=24 * 20)], None, None)
    assert store.articles({"jvns": BY_ID["jvns"]}) == []


def test_published_at_kept_on_refetch(store):
    first = item("https://jvns.ca/x", hours_ago=5)
    store.save_fetch("jvns", [first], None, None)
    store.save_fetch("jvns", [item("https://jvns.ca/x", "Edited", hours_ago=0)], None, None)
    [a] = store.articles({"jvns": BY_ID["jvns"]})
    assert a.title == "Edited" and a.published_at == first.published_at


def test_due_and_cache_headers(store):
    hn, jvns = BY_ID["hn"], BY_ID["jvns"]
    assert store.due([hn, jvns]) == [hn, jvns]
    store.save_fetch("hn", [], '"abc"', None)
    assert store.due([hn, jvns]) == [jvns]
    assert store.due([hn], now=datetime.now(UTC) + timedelta(minutes=hn.refresh_minutes + 1)) == [hn]
    store.save_fetch("hn", None, None, None)  # 304 keeps the old etag
    assert store.cache_headers("hn") == ('"abc"', None)
