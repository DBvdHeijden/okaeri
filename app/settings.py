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
# History is chronological by design; every other tab sorts by "latest" or "recommended".
ALL_TAB = {"name": "All", "slug": "all", "tags": (), "sources": (), "history": False, "builtin": True, "sort": "latest"}
HISTORY_TAB = {"name": "History", "slug": "history", "tags": (), "sources": (), "history": True, "builtin": True, "sort": "latest"}


def load() -> dict:
    if not PATH.exists():
        shutil.copy(EXAMPLE, PATH)
    # settings.json overrides the defaults key by key, so new settings reach existing users.
    return json.loads(EXAMPLE.read_text()) | json.loads(PATH.read_text())


def reset() -> None:
    shutil.copy(EXAMPLE, PATH)


def save(settings: dict) -> None:
    PATH.write_text(json.dumps(settings, indent=2) + "\n")


def enabled_sources() -> list[str]:
    return load()["sources"]["enabled"]


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def all_tabs() -> list[dict]:
    """Every tab in order, hidden ones included: All, the custom tabs, History."""
    stored = load()["tabs"]
    builtin = {t["builtin"]: t for t in stored if "builtin" in t}
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
            "sort": sort_of(t),
        }
        for t in custom[:MAX_TABS]
    ]
    all_tab, history_tab = builtin.get("all", {}), builtin.get("history", {})
    return [
        {**ALL_TAB, "hidden": all_tab.get("hidden", False), "sort": sort_of(all_tab)},
        *custom,
        {**HISTORY_TAB, "hidden": history_tab.get("hidden", False)},
    ]


def sort_of(tab: dict) -> str:
    return "recommended" if tab.get("sort") == "recommended" else "latest"


def tabs() -> list[dict]:
    """The visible tabs. Nothing picked means everything; the history tab lists opened links."""
    return [t for t in all_tabs() if not t["hidden"]] or [ALL_TAB]


def name() -> str:
    return load()["name"]


def set_name(name: str) -> None:
    settings = load()
    settings["name"] = name.strip()[:40]
    save(settings)


def languages() -> list[str]:
    return load()["languages"]


def set_languages(languages: list[str]) -> None:
    settings = load()
    settings["languages"] = languages
    save(settings)


def interests() -> dict:
    return load()["interests"]


def set_interests(formats: list[str], topics: list[str]) -> None:
    settings = load()
    settings["interests"] = {"formats": formats, "topics": topics}
    save(settings)


def weights() -> dict[str, float]:
    return load()["ranking"]


def set_weights(weights: dict[str, float]) -> None:
    settings = load()
    # Tenths: the dials glide freely, but a weight is one of 0, 0.1, ... 1.
    settings["ranking"] = {k: round(min(max(weights[k], 0.0), 1.0), 1) for k in settings["ranking"]}
    save(settings)


def set_enabled_sources(source_ids: list[str]) -> None:
    settings = load()
    settings["sources"]["enabled"] = source_ids
    save(settings)


def set_sort(tab_slug: str, sort: str) -> bool:
    """Set one tab's sort, from the switch on the homepage. False if there's no such tab."""
    settings = load()
    for tab in settings["tabs"]:
        if tab.get("builtin", slug(tab.get("name", ""))) == tab_slug and tab_slug != "history":
            tab["sort"] = sort
            save(settings)
            return True
    return False


def set_tabs(rows: list[dict]) -> None:
    """Rows from the tab editor: custom tabs need a unique name; All and History can only be hidden."""
    builtin = {row["builtin"]: row for row in rows if row.get("builtin") in ("all", "history")}
    taken, custom = {"all", "history"}, []
    for row in rows:
        name = str(row.get("name") or "").strip()
        if row.get("builtin") or not slug(name) or slug(name) in taken:
            continue
        taken.add(slug(name))
        tags = [t for t in row.get("tags", []) if t in FORMATS | TOPICS]
        # Picked sources the formats and topics no longer leave over would narrow invisibly: drop them.
        sources = [s for s in row.get("sources", []) if s in BY_ID and tab_covers(BY_ID[s], tags, ())]
        custom.append({"name": name, "tags": tags, "sources": sources, "hidden": bool(row.get("hidden")), "sort": sort_of(row)})
    settings = load()
    settings["tabs"] = [
        {"builtin": "all", "hidden": bool(builtin.get("all", {}).get("hidden")), "sort": sort_of(builtin.get("all", {}))},
        *custom[:MAX_TABS],
        {"builtin": "history", "hidden": bool(builtin.get("history", {}).get("hidden"))},
    ]
    save(settings)
