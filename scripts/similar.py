"""Try out the article embeddings: the feed items nearest to a query or to another article.

    uv run scripts/similar.py "some query text"
    uv run scripts/similar.py --item <id>    # the id from /r/<id>
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # run as a file, so the repo root isn't on the path

import numpy as np

from app import settings
from app.embed import MODEL, load_embedder
from app.sources import BY_ID
from app.store import default_path, open_store

parser = argparse.ArgumentParser()
parser.add_argument("query", nargs="?")
parser.add_argument("--item")
args = parser.parse_args()
if bool(args.query) == bool(args.item):
    parser.error("give either a query or --item")

store = open_store(default_path())
vectors = {key: np.frombuffer(blob, np.float32) for key, blob in store.embeddings(MODEL).items()}
feed = [a for a in store.articles({i: BY_ID[i] for i in settings.enabled_sources() if i in BY_ID}) if a.key in vectors]

if args.item:
    article = store.article(args.item, BY_ID)
    if not article or article.key not in vectors:
        sys.exit(f"no embedded item {args.item}")
    target = vectors[article.key]
    feed = [a for a in feed if a.key != article.key]
else:
    target = load_embedder()([f"task: search result | query: {args.query}"])[0]

scores = np.array([vectors[a.key] for a in feed]) @ target
for i in np.argsort(-scores)[:10]:
    print(f"{scores[i]:.3f}  {feed[i].source[:22]:<22}  {feed[i].title}")
