"""User settings in settings.json: plain JSON, owned by the settings (onboarding) page."""

import json
import logging
import re
import shutil

from app import ROOT
from app.sources import BY_ID, FORMATS, TOPICS, known_sources, known_tags, tab_covers

log = logging.getLogger("okaeri")

PATH = ROOT / "settings.json"
EXAMPLE = ROOT / "settings.example.json"
MAX_TABS = 6  # custom tabs, besides All and History
ALL_TAB = {"name": "All", "slug": "all", "tags": (), "sources": (), "history": False, "builtin": True}
HISTORY_TAB = {"name": "History", "slug": "history", "tags": (), "sources": (), "history": True, "builtin": True}


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


def all_tabs() -> list[dict]:
    """Every tab in order, hidden ones included: All, the custom tabs, History."""
    stored = load()["tabs"]
    builtin_hidden = {t["builtin"]: t["hidden"] for t in stored if "builtin" in t}
    custom = [t for t in stored if "builtin" not in t]
    if len(custom) > MAX_TABS:
        log.warning("showing the first %d tabs; ignoring %s", MAX_TABS, [t["name"] for t in custom[MAX_TABS:]])
    custom = [
        {
            "name": t["name"],
            "slug": slug(t["name"]),
            "tags": known_tags(t["tags"], f"tab {t['name']!r}"),
            "sources": known_sources(t.get("sources", []), f"tab {t['name']!r}"),
            "history": False,
            "builtin": False,
            "hidden": t.get("hidden", False),
        }
        for t in custom[:MAX_TABS]
    ]
    return [
        {**ALL_TAB, "hidden": builtin_hidden.get("all", False)},
        *custom,
        {**HISTORY_TAB, "hidden": builtin_hidden.get("history", False)},
    ]


def tabs() -> list[dict]:
    """The visible tabs. Nothing picked means everything; the history tab lists opened links."""
    return [t for t in all_tabs() if not t["hidden"]] or [ALL_TAB]


def interests() -> dict:
    return load()["interests"]


def set_interests(formats: list[str], topics: list[str]) -> None:
    settings = load()
    settings["interests"] = {"formats": formats, "topics": topics}
    save(settings)


def set_enabled_sources(source_ids: list[str]) -> None:
    settings = load()
    settings["sources"]["enabled"] = source_ids
    save(settings)


def set_tabs(rows: list[dict]) -> None:
    """Rows from the tab editor: custom tabs need a unique name; All and History can only be hidden."""
    builtin_hidden = {row["builtin"]: bool(row.get("hidden")) for row in rows if row.get("builtin") in ("all", "history")}
    taken, custom = {"all", "history"}, []
    for row in rows:
        name = str(row.get("name") or "").strip()
        if row.get("builtin") or not slug(name) or slug(name) in taken:
            continue
        taken.add(slug(name))
        tags = [t for t in row.get("tags", []) if t in FORMATS | TOPICS]
        # Picked sources the formats and topics no longer leave over would narrow invisibly: drop them.
        sources = [s for s in row.get("sources", []) if s in BY_ID and tab_covers(BY_ID[s], tags, ())]
        custom.append({"name": name, "tags": tags, "sources": sources, "hidden": bool(row.get("hidden"))})
    settings = load()
    settings["tabs"] = [
        {"builtin": "all", "hidden": builtin_hidden.get("all", False)},
        *custom[:MAX_TABS],
        {"builtin": "history", "hidden": builtin_hidden.get("history", False)},
    ]
    save(settings)
