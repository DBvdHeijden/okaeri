"""The curated source catalog, loaded from catalog/sources.json.

arXiv entries use the API because the arXiv RSS feeds are empty on weekends.
Reddit refreshes slowly because it rate-limits (429) quickly.
"""

import json

from app import ROOT
from app.models import Source

SOURCES: list[Source] = [Source(**s) for s in json.loads((ROOT / "catalog" / "sources.json").read_text())]
BY_ID: dict[str, Source] = {s.id: s for s in SOURCES}
