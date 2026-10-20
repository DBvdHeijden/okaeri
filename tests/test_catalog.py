import numpy as np

from app.embed import CATALOG_VECTORS, MODEL, catalog_texts, text_key


def test_catalog_vectors_match_the_catalog():
    # Onboarding's map reads these; after changing sources or tags, run `uv run scripts/sample_sources.py`.
    shipped = np.load(CATALOG_VECTORS)
    assert shipped["model"] == MODEL
    assert set(shipped["keys"].tolist()) == {text_key(t) for t in catalog_texts()}
