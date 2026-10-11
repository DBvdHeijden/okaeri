from datetime import UTC, datetime, timedelta

import pytest

from okaeri.models import FetchedItem
from okaeri.store import Store, open_store


@pytest.fixture
def store(tmp_path, monkeypatch) -> Store:
    path = tmp_path / "okaeri.db"
    monkeypatch.setenv("OKAERI_DB", str(path))
    return open_store(path)


def item(url: str, title: str = "", hours_ago: float = 1, **kw) -> FetchedItem:
    from okaeri.fetch import item_key

    return FetchedItem(
        key=item_key(url),
        url=url,
        title=title or url,
        published_at=datetime.now(UTC) - timedelta(hours=hours_ago),
        **kw,
    )
