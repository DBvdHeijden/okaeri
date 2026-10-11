"""User settings in settings.json: plain JSON, owned by the settings (onboarding) page."""

import json
import shutil

from app import ROOT

PATH = ROOT / "settings.json"


def load() -> dict:
    if not PATH.exists():
        shutil.copy(ROOT / "settings.example.json", PATH)
    return json.loads(PATH.read_text())


def save(settings: dict) -> None:
    PATH.write_text(json.dumps(settings, indent=2) + "\n")


def enabled_sources() -> list[str]:
    return load()["sources"]["enabled"]


def set_enabled_sources(source_ids: list[str]) -> None:
    settings = load()
    settings["sources"]["enabled"] = source_ids
    save(settings)
