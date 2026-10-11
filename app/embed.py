"""Article embeddings with EmbeddingGemma 2, run locally. An experiment: rank() doesn't use them yet.

    python -m app.embed    # embed everything pending, then exit

The refresh loop runs this as a short-lived child process, so the server never holds the model in memory.
"""

import logging
import os
import time
from collections.abc import Callable
from functools import partial

import numpy as np

from app import ROOT, settings
from app.models import Article
from app.sources import BY_ID
from app.store import Store, article_id, default_path, open_store

log = logging.getLogger("okaeri.embed")

# The ONNX export of the 270M text model, 8-bit; vision and audio are separate files we never download.
REPO = "onnx-community/embeddinggemma-2-ONNX"
REVISION = "daa72c51243991dfcaf9f9137d2c573d8f7790c0"
DIMS = 256  # Matryoshka: the model card calls quality near-lossless down to 256
MODEL = f"embeddinggemma-2-text@{DIMS}"  # stored with each vector, so a new model or size re-embeds everything
BATCH = 16  # faster than 32 and ~600 MB less peak RAM, measured on 200 feed items
SUMMARY_CHARS = 500
MAX_TOKENS = 256  # the title and the start of the summary carry most of the meaning; caps the peak per batch

Embedder = Callable[[list[str]], np.ndarray]


def load_embedder() -> Embedder:
    """Download the model on first use; returns texts -> unit float32 vectors of DIMS."""
    # Imported here so the server, which only checks what's pending, never loads them.
    import onnxruntime as ort
    from huggingface_hub import snapshot_download
    from huggingface_hub.errors import LocalEntryNotFoundError
    from huggingface_hub.utils import logging as hf_logging
    from tokenizers import Tokenizer

    hf_logging.set_verbosity_error()  # it warns "remote repo cannot be accessed" on every local load

    download = partial(
        snapshot_download,
        REPO,
        revision=REVISION,
        allow_patterns=["onnx/model_quantized.onnx*", "tokenizer.json"],
        local_dir=ROOT / "data" / "models" / "embeddinggemma-2",
    )
    try:
        path = download(local_files_only=True)  # no Hub lookup when we have it, so it works offline
    except LocalEntryNotFoundError:
        path = download()
    options = ort.SessionOptions()
    options.intra_op_num_threads = 2  # a background job: never take every core
    options.inter_op_num_threads = 1
    session = ort.InferenceSession(f"{path}/onnx/model_quantized.onnx", options)
    tokenizer = Tokenizer.from_file(f"{path}/tokenizer.json")
    tokenizer.enable_padding(pad_id=tokenizer.token_to_id("<pad>"), pad_token="<pad>")
    tokenizer.enable_truncation(MAX_TOKENS)
    no_media = np.zeros((0, 512), np.float32)  # the export takes image, video and audio features too

    def embed(texts: list[str]) -> np.ndarray:
        encodings = tokenizer.encode_batch(texts)
        # sentence_embedding is mean-pooled and L2-normalised, as in the official model.
        (vectors,) = session.run(["sentence_embedding"], {
            "input_ids": np.array([e.ids for e in encodings], np.int64),
            "attention_mask": np.array([e.attention_mask for e in encodings], np.int64),
            "image_features": no_media,
            "video_features": no_media,
            "audio_features": no_media,
        })
        vectors = vectors[:, :DIMS]
        return (vectors / np.linalg.norm(vectors, axis=1, keepdims=True)).astype(np.float32)

    return embed


def document(article: Article) -> str:
    if not article.summary:
        return f"title: none | text: {article.title}"
    return f"title: {article.title} | text: {article.summary[:SUMMARY_CHARS]}"


def pending(store: Store) -> list[Article]:
    """What's in the feed, plus everything with an event (the recommender's training signal), not yet embedded."""
    done = store.embedded_keys(MODEL)
    feed = store.articles({i: BY_ID[i] for i in settings.enabled_sources() if i in BY_ID})
    todo = {a.key: a for a in feed if a.key not in done}
    for key in {e.key for e in store.events()} - done - todo.keys():
        if article := store.article(article_id(key), BY_ID):
            todo[key] = article
    return list(todo.values())


def embed_new(store: Store, embed: Embedder) -> None:
    started = time.monotonic()
    articles = sorted(pending(store), key=lambda a: len(document(a)))  # similar lengths per batch: less padding
    for start in range(0, len(articles), BATCH):
        batch = articles[start : start + BATCH]
        vectors = embed([document(a) for a in batch])
        store.save_embeddings(MODEL, [(a.key, v.tobytes()) for a, v in zip(batch, vectors)])
    if articles:
        log.info("embedded %d items in %.1fs", len(articles), time.monotonic() - started)


def main() -> None:
    if hasattr(os, "nice"):
        os.nice(19)  # a background job: the server and everything else on the machine go first
    logging.basicConfig(level=logging.INFO)
    started = time.monotonic()
    embed = load_embedder()
    log.info("loaded the embedding model in %.1fs", time.monotonic() - started)
    embed_new(open_store(default_path()), embed)


if __name__ == "__main__":
    main()
