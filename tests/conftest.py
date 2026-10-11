from datetime import UTC, datetime, timedelta

import pytest

from app import settings
from app.models import FetchedItem
from app.store import Store, open_store


@pytest.fixture
def store(tmp_path, monkeypatch) -> Store:
    monkeypatch.setattr(settings, "PATH", tmp_path / "settings.json")
    path = tmp_path / "okaeri.db"
    monkeypatch.setenv("OKAERI_DB", str(path))
    return open_store(path)


def item(url: str, title: str = "", hours_ago: float = 1, **kw) -> FetchedItem:
    from app.fetch import item_key

    return FetchedItem(
        key=item_key(url),
        url=url,
        title=title or url,
        published_at=datetime.now(UTC) - timedelta(hours=hours_ago),
        **kw,
    )
