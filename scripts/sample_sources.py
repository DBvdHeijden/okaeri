"""Write each source's latest titles into catalog/sources.json, so onboarding can match your interests against what a
source actually publishes, not just its description. Then embed the catalog into catalog/vectors.npz, so onboarding's
map doesn't have to. Rerun when you add sources, or now and then.

    uv run scripts/sample_sources.py
"""

import asyncio
import json
import sqlite3
import subprocess
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # run as a file, so the repo root isn't on the path

from app import ROOT, fetch
from app.fetch import refresh
from app.sources import SOURCES
from app.store import Store

SAMPLE_SIZE = 10
CATALOG = ROOT / "catalog" / "sources.json"

with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp) / "sample.db"
    store = Store(path)
    # Keep old posts too: a blog that posts rarely is still about what it posts.
    fetch.MAX_AGE = timedelta(days=100 * 365)
    store.prune = lambda: None
    asyncio.run(refresh(store, SOURCES))
    with sqlite3.connect(path) as db:
        latest = {
            s.id: [title for title, in db.execute(
                "SELECT title FROM items WHERE source_id = ? ORDER BY published_at DESC LIMIT ?", (s.id, SAMPLE_SIZE)
            )]
            for s in SOURCES
        }

catalog = json.loads(CATALOG.read_text())
for raw in catalog:
    # A feed that failed this time keeps the sample it had.
    if titles := latest[raw["id"]]:
        raw["sample"] = titles
    else:
        print(f"no items from {raw['id']}, keeping its old sample", file=sys.stderr)
CATALOG.write_text("[\n" + ",\n".join(f"  {json.dumps(raw, ensure_ascii=False)}" for raw in catalog) + "\n]\n")
# A new process: this one loaded the catalog before the new samples were written.
subprocess.run([sys.executable, "-m", "app.embed", "catalog"], cwd=ROOT, check=True)
