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


def set_tabs(*tabs):
    settings.save({**settings.load(), "tabs": [{"name": name, "tags": tags} for name, tags in tabs]})


def test_tab_filter(store):
    seed(store)  # simonw: blog ai software, hn: forum, arxiv-cs.lg: paper ai
    assert titles(client.get("/?tab=papers").text) == ["A paper"]
    assert titles(client.get("/?tab=ai").text) == ["Blog post", "A paper"]
    assert titles(client.get("/?tab=nope").text) == titles(client.get("/").text)


def test_tab_matches_any_tag_within_a_group(store):
    settings.set_enabled_sources(["jvns", "tao", "arxiv-cs.lg"])
    store.save_fetch("jvns", [item("https://jvns.ca/a", "Software post", hours_ago=1)], None, None)
    store.save_fetch("tao", [item("https://terrytao.wordpress.com/a", "Maths post", hours_ago=2)], None, None)
    store.save_fetch("arxiv-cs.lg", [item("https://arxiv.org/abs/2610.00001", "AI paper", hours_ago=3)], None, None)
    set_tabs(("Code or maths", ["software", "math"]), ("Blogs or papers", ["blog", "paper"]))
    assert titles(client.get("/?tab=code-or-maths").text) == ["Software post", "Maths post"]
    assert titles(client.get("/?tab=blogs-or-papers").text) == ["Software post", "Maths post", "AI paper"]


def test_tab_needs_every_group_to_match(store):
    seed(store)
    set_tabs(("AI papers", ["ai", "paper"]))
    assert titles(client.get("/?tab=ai-papers").text) == ["A paper"]  # not the AI blog post


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
    monkeypatch.setattr(server, "rank", lambda arts, *args: sorted(arts, key=lambda a: a.title))
    assert titles(client.get("/").text) == ["A paper", "Blog post", "Forum link"]


def test_show_more(store):
    settings.set_enabled_sources(["simonw"])
    store.save_fetch("simonw", [item(f"https://simonwillison.net/{i}") for i in range(server.PAGE_SIZE + 5)], None, None)
    html = client.get("/").text
    assert len(titles(html)) == server.PAGE_SIZE
    more = f'href="/?tab=all&amp;n={2 * server.PAGE_SIZE}#item-{server.PAGE_SIZE + 1}"'
    assert more in html
    html = client.get(f"/?n={2 * server.PAGE_SIZE}").text
    assert len(titles(html)) == server.PAGE_SIZE + 5 and "Show more" not in html


def test_onboarding_lists_sources_and_checks_selected(store):
    settings.set_enabled_sources(["hn"])
    html = client.get("/onboarding/sources").text
    assert all(s.name in html for s in SOURCES)
    assert re.search(r'value="hn" checked', html)
    assert not re.search(r'value="lobsters" checked', html)


def test_onboarding_submit_persists(store):
    r = client.post("/onboarding/sources", data={"sources": ["hn", "arxiv-cs.lg", "bogus"]}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/onboarding/sample"
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
    link = re.search(rf'<a href="/r/{article_id("e.com/a")}\?to=thread"[^>]*>(.*?)</a>', html, re.S)
    assert link and 'title="1 comment"' in link.group(1)


def tab_labels(html: str) -> list[str]:
    return re.findall(r'<a href="/\?tab=[\w-]+"[^>]*>([^<]+)</a>', html)


def test_tabs_come_from_settings(store):
    seed(store)
    assert tab_labels(client.get("/").text) == ["All", "AI", "Papers", "Science", "Tech", "World", "History"]
    set_tabs(*((f"T{i}", ["ai"]) for i in range(8)))
    assert tab_labels(client.get("/").text) == ["All", "T0", "T1", "T2", "T3", "T4", "T5", "History"]


def open_story(key):
    r = client.get(f"/r/{article_id(key)}", follow_redirects=False)
    assert r.status_code == 302


def test_history_lists_opened_stories_latest_first(store):
    seed(store)
    open_story("example.com/news")
    open_story("simonwillison.net/a")
    open_story("example.com/news")  # reopened: moves to top, listed once
    html = client.get("/?tab=history").text
    assert titles(html) == ["Forum link", "Blog post"]
    assert ">just now</time>" in html and " ago" not in html and "data-hide" not in html


def test_history_empty_state(store):
    seed(store)
    assert "Nothing opened yet." in client.get("/?tab=history").text


def test_unknown_article_is_404(store):
    seed(store)
    assert client.get("/r/nope").status_code == 404
    assert client.post("/hide/nope").status_code == 404


def test_hide_and_unhide(store):
    seed(store)
    hidden = article_id("example.com/news")
    r = client.post(f"/hide/{hidden}", headers={"referer": "/?tab=ai"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/?tab=ai"
    assert titles(client.get("/").text) == ["Blog post", "A paper"]
    client.post(f"/unhide/{hidden}")
    assert titles(client.get("/").text) == ["Blog post", "Forum link", "A paper"]
