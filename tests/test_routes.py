import re

from fastapi.testclient import TestClient

from okaeri import server
from okaeri.sources import SOURCES
from tests.conftest import item

# No `with`: the lifespan (and so the background fetcher) does not run.
client = TestClient(server.app)


def titles(html: str) -> list[str]:
    return re.findall(r'class="title" href="[^"]*" rel="noopener">([^<]+)<', html)


def seed(store):
    store.set_selected(["simonw", "hn", "arxiv-cs.lg"])
    store.save_fetch("simonw", [item("https://simonwillison.net/a", "Blog post", hours_ago=2)], None, None)
    store.save_fetch("hn", [
        item("https://simonwillison.net/a/", "Blog post (HN title)", hours_ago=1,
             discussion_url="https://news.ycombinator.com/item?id=1"),
        item("https://example.com/news", "Forum link", hours_ago=3,
             discussion_url="https://news.ycombinator.com/item?id=2"),
    ], None, None)
    store.save_fetch("arxiv-cs.lg", [item("https://arxiv.org/abs/2610.00001v2", "A paper", hours_ago=5)], None, None)


def test_no_selection_redirects_to_onboarding(store):
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/onboarding"


def test_home_merges_and_orders(store):
    seed(store)
    html = client.get("/").text
    assert titles(html) == ["Blog post", "Forum link", "A paper"]
    assert "also on Hacker News" in html
    assert 'href="https://news.ycombinator.com/item?id=1"' in html


def test_kind_filter(store):
    seed(store)
    assert titles(client.get("/?kind=paper").text) == ["A paper"]
    assert titles(client.get("/?kind=nope").text) == titles(client.get("/").text)


def test_only_selected_sources_shown(store):
    seed(store)
    store.set_selected(["arxiv-cs.lg"])
    assert titles(client.get("/").text) == ["A paper"]


def test_pending_state(store):
    store.set_selected(["lobsters"])
    html = client.get("/").text
    assert "Fetching your sources" in html and 'http-equiv="refresh"' in html


def test_routes_go_through_rank(store, monkeypatch):
    seed(store)
    monkeypatch.setattr(server, "rank", lambda arts: sorted(arts, key=lambda a: a.title))
    assert titles(client.get("/").text) == ["A paper", "Blog post", "Forum link"]


def test_list_capped(store, monkeypatch):
    store.set_selected(["simonw"])
    store.save_fetch("simonw", [item(f"https://simonwillison.net/{i}") for i in range(120)], None, None)
    assert len(titles(client.get("/").text)) == server.MAX_ARTICLES


def test_onboarding_lists_sources_and_checks_selected(store):
    store.set_selected(["hn"])
    html = client.get("/onboarding").text
    assert all(s.name in html for s in SOURCES)
    assert re.search(r'value="hn" checked', html)
    assert not re.search(r'value="lobsters" checked', html)


def test_onboarding_submit_persists(store):
    r = client.post("/onboarding", data={"sources": ["hn", "arxiv-cs.lg", "bogus"]}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/"
    assert store.selected() == {"hn", "arxiv-cs.lg"}
