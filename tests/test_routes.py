import re

from fastapi.testclient import TestClient

from app import server, settings
from app.sources import SOURCES
from app.store import article_id
from tests.conftest import item

# No `with`: the lifespan (and so the background fetcher) does not run.
client = TestClient(server.app)


def titles(html: str) -> list[str]:
    return re.findall(r'class="title" href="[^"]*" target="_blank" rel="noopener">([^<]+)<', html)


def seed(store):
    settings.set_enabled_sources(["simonw", "hn", "arxiv-cs.lg"])
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
    thread = f'href="/r/{article_id("simonwillison.net/a")}?to=thread"'
    assert thread in html
    r = client.get(f"/r/{article_id('simonwillison.net/a')}?to=thread", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "https://news.ycombinator.com/item?id=1"


def test_kind_filter(store):
    seed(store)
    assert titles(client.get("/?kind=paper").text) == ["A paper"]
    assert titles(client.get("/?kind=nope").text) == titles(client.get("/").text)


def test_only_selected_sources_shown(store):
    seed(store)
    settings.set_enabled_sources(["arxiv-cs.lg"])
    assert titles(client.get("/").text) == ["A paper"]


def test_pending_state(store):
    settings.set_enabled_sources(["lobsters"])
    html = client.get("/").text
    assert "Fetching your sources" in html and 'http-equiv="refresh"' in html


def test_routes_go_through_rank(store, monkeypatch):
    seed(store)
    monkeypatch.setattr(server, "rank", lambda arts, events, settings: sorted(arts, key=lambda a: a.title))
    assert titles(client.get("/").text) == ["A paper", "Blog post", "Forum link"]


def test_list_capped(store, monkeypatch):
    settings.set_enabled_sources(["simonw"])
    store.save_fetch("simonw", [item(f"https://simonwillison.net/{i}") for i in range(120)], None, None)
    assert len(titles(client.get("/").text)) == server.MAX_ARTICLES


def test_onboarding_lists_sources_and_checks_selected(store):
    settings.set_enabled_sources(["hn"])
    html = client.get("/onboarding").text
    assert all(s.name in html for s in SOURCES)
    assert re.search(r'value="hn" checked', html)
    assert not re.search(r'value="lobsters" checked', html)


def test_onboarding_submit_persists(store):
    r = client.post("/onboarding", data={"sources": ["hn", "arxiv-cs.lg", "bogus"]}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/"
    assert settings.enabled_sources() == ["hn", "arxiv-cs.lg"]


def test_favicons():
    for path in ("/favicon.ico", "/static/favicon.svg", "/static/favicon-32.png", "/static/apple-touch-icon.png"):
        assert client.get(path).status_code == 200


def test_counts_shown_with_comment_link(store):
    settings.set_enabled_sources(["hn"])
    store.save_fetch("hn", [item("https://e.com/a", "Counted", score=1516, comments=1,
                                 discussion_url="https://news.ycombinator.com/item?id=9")], None, None)
    html = client.get("/").text
    assert "1,516 points" in html
    assert f'<a href="/r/{article_id("e.com/a")}?to=thread" target="_blank" rel="noopener">1 comment</a>' in html


def tab_labels(html: str) -> list[str]:
    return re.findall(r'<a href="/\?kind=\w+"[^>]*>(\w+)</a>', html)


def test_tabs_only_for_followed_kinds(store):
    seed(store)  # blog, forum, paper
    html = client.get("/").text
    assert tab_labels(html) == ["All", "Papers", "Blogs", "Forums", "History"]
    assert titles(client.get("/?kind=news").text) == titles(html)  # unfollowed kind falls back to all


def test_single_kind_shows_only_all_and_history(store):
    settings.set_enabled_sources(["simonw", "jvns"])
    assert tab_labels(client.get("/").text) == ["All", "History"]


def open_story(key):
    r = client.get(f"/r/{article_id(key)}", follow_redirects=False)
    assert r.status_code == 302


def test_history_lists_opened_stories_latest_first(store):
    seed(store)
    open_story("example.com/news")
    open_story("simonwillison.net/a")
    open_story("example.com/news")  # reopened: moves to top, listed once
    html = client.get("/?kind=history").text
    assert titles(html) == ["Forum link", "Blog post"]
    assert ">just now</time>" in html and " ago" not in html and "data-hide" not in html


def test_history_empty_state(store):
    seed(store)
    assert "Nothing opened yet." in client.get("/?kind=history").text


def test_unknown_article_is_404(store):
    seed(store)
    assert client.get("/r/nope").status_code == 404
    assert client.post("/hide/nope").status_code == 404


def test_hide_and_unhide(store):
    seed(store)
    hidden = article_id("example.com/news")
    r = client.post(f"/hide/{hidden}", headers={"referer": "/?kind=forum"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/?kind=forum"
    assert titles(client.get("/").text) == ["Blog post", "A paper"]
    client.post(f"/unhide/{hidden}")
    assert titles(client.get("/").text) == ["Blog post", "Forum link", "A paper"]
