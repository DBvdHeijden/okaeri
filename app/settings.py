"""User settings in settings.json: plain JSON, owned by the settings (onboarding) page."""

import json
import logging
import re
import shutil

from app import ROOT
from app.sources import known_tags

log = logging.getLogger("okaeri")

PATH = ROOT / "settings.json"
EXAMPLE = ROOT / "settings.example.json"
MAX_TABS = 6


def load() -> dict:
    if not PATH.exists():
        shutil.copy(EXAMPLE, PATH)
    # settings.json overrides the defaults key by key, so new settings reach existing users.
    return json.loads(EXAMPLE.read_text()) | json.loads(PATH.read_text())


def save(settings: dict) -> None:
    PATH.write_text(json.dumps(settings, indent=2) + "\n")


def enabled_sources() -> list[str]:
    return load()["sources"]["enabled"]


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def tabs() -> list[dict]:
    """The user's tabs as {name, slug, tags}; "All" and "History" are added by the page."""
    tabs = load()["tabs"]
    if len(tabs) > MAX_TABS:
        log.warning("showing the first %d tabs; ignoring %s", MAX_TABS, [t["name"] for t in tabs[MAX_TABS:]])
    return [
        {"name": t["name"], "slug": slug(t["name"]), "tags": known_tags(t["tags"], f"tab {t['name']!r}")}
        for t in tabs[:MAX_TABS]
    ]


def set_enabled_sources(source_ids: list[str]) -> None:
    settings = load()
    settings["sources"]["enabled"] = source_ids
    save(settings)
