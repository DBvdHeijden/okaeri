import re

from fastapi.testclient import TestClient

from okaeri import mock, server

client = TestClient(server.app)


def row_ids(html: str) -> list[str]:
    return re.findall(r'class="row" data-id="([^"]+)"', html)


def by_id() -> dict[str, mock.Article]:
    return {a.id: a for a in mock.articles()}


def test_home_newest_first():
    r = client.get("/")
    assert r.status_code == 200
    ids = row_ids(r.text)
    assert len(ids) == len(mock.articles())
    times = [by_id()[i].published_at for i in ids]
    assert times == sorted(times, reverse=True)


def test_kind_filter():
    ids = row_ids(client.get("/?kind=paper").text)
    assert ids and all(by_id()[i].kind == "paper" for i in ids)


def test_unknown_kind_falls_back_to_all():
    assert row_ids(client.get("/?kind=nope").text) == row_ids(client.get("/").text)


def test_list_capped(monkeypatch):
    many = mock.articles() * 10
    monkeypatch.setattr(server.mock, "articles", lambda: many)
    assert len(row_ids(client.get("/").text)) == server.MAX_ARTICLES


def test_routes_go_through_rank(monkeypatch):
    monkeypatch.setattr(server, "rank", lambda arts: sorted(arts, key=lambda a: a.id, reverse=True))
    ids = row_ids(client.get("/").text)
    assert ids == sorted(ids, reverse=True)


def test_onboarding():
    r = client.get("/onboarding")
    assert r.status_code == 200
    assert all(s.name in r.text for s in mock.SOURCES)


def test_onboarding_submit_redirects():
    r = client.post("/onboarding", data={"sources": ["hn", "arxiv-cs-lg"]}, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/"
