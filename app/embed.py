"""Article embeddings with EmbeddingGemma 2, run locally; rank() uses them for Recommended.

    python -m app.embed          # embed everything pending, then exit
    python -m app.embed serve    # embed texts as they come: a JSON list per line on stdin, their vectors on stdout
    python -m app.embed catalog  # write the catalog's vectors to catalog/vectors.npz (scripts/sample_sources.py runs it)

The refresh loop runs the first as a short-lived child process, so the server never holds the model in memory;
onboarding's map runs the second (LiveEmbedder) for the interests you write there.
"""

import asyncio
import hashlib
import json
import logging
import os
import sys
import time
from collections.abc import Callable
from functools import partial

import numpy as np

from app import ROOT, settings
from app.models import Article, Source
from app.sources import BY_ID, SOURCES, TAG_DESCRIPTIONS
from app.store import Store, article_id, default_path, open_store

log = logging.getLogger("okaeri.embed")

# The ONNX export of the 270M text model, 8-bit; vision and audio are separate files we never download.
REPO = "onnx-community/embeddinggemma-2-ONNX"
REVISION = "daa72c51243991dfcaf9f9137d2c573d8f7790c0"
DIMS = 256  # Matryoshka: the model card calls quality near-lossless down to 256
MODEL = f"embeddinggemma-2-text@{DIMS}"  # stored with each vector, so a new model or size re-embeds everything
BATCH = 16  # faster than 32 and ~600 MB less peak RAM, measured on 200 feed items
SUMMARY_CHARS = 500
MODEL_DIR = ROOT / "data" / "models" / "embeddinggemma-2"
MAX_TOKENS = 256  # the title and the start of the summary carry most of the meaning; caps the peak per batch
CATALOG_VECTORS = ROOT / "catalog" / "vectors.npz"

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
        local_dir=MODEL_DIR,
    )
    try:
        path = download(local_files_only=True)  # no Hub lookup when we have it, so it works offline
    except LocalEntryNotFoundError:
        log.info("downloading the embedding model, ~330 MB, one time")
        path = download()
        log.info("downloaded the embedding model to %s", path)
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
        (vectors,) = session.run(
            ["sentence_embedding"],
            {
                "input_ids": np.array([e.ids for e in encodings], np.int64),
                "attention_mask": np.array([e.attention_mask for e in encodings], np.int64),
                "image_features": no_media,
                "video_features": no_media,
                "audio_features": no_media,
            },
        )
        vectors = vectors[:, :DIMS]
        return (vectors / np.linalg.norm(vectors, axis=1, keepdims=True)).astype(np.float32)

    return embed


def stored_vectors(store: Store) -> dict[str, np.ndarray]:
    return {key: np.frombuffer(blob, np.float32) for key, blob in store.embeddings(MODEL).items()}


def model_downloaded() -> bool:
    # The download lands in a temporary file and is moved here when complete.
    return (MODEL_DIR / "onnx" / "model_quantized.onnx_data").exists()


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


# Texts that aren't stories: the interests you wrote in onboarding, and the catalog it's matched against (sources, topics).
# Stored with the story vectors, keyed by the text itself, so a changed text gets a vector of its own.
def text_key(text: str) -> str:
    return "okaeri:" + hashlib.sha1(text.encode()).hexdigest()[:16]


def about_document(about: str) -> str:
    return f"task: search result | query: {about}"  # EmbeddingGemma's prompt for a query, matched against documents


def source_document(source: Source) -> str:
    # One-line descriptions are thin; its topics' descriptions and latest titles say more about what it covers.
    topics = " ".join(TAG_DESCRIPTIONS[t] for t in source.tags)
    sample = "; ".join(source.sample)
    return f"title: {source.name} | text: {source.description} {topics} {sample}".strip()


def topic_document(topic: str) -> str:
    return f"title: {topic} | text: {TAG_DESCRIPTIONS[topic]}"


def catalog_texts() -> list[str]:
    return [source_document(s) for s in SOURCES] + [topic_document(t) for t in TAG_DESCRIPTIONS]


def pending_texts(store: Store) -> list[str]:
    texts = [about_document(a) for a in settings.about()] + catalog_texts()
    done = store.embedded_keys(MODEL)
    return [t for t in texts if text_key(t) not in done]


def write_catalog_vectors(embed: Embedder) -> None:
    texts = catalog_texts()
    vectors = np.vstack([embed(texts[start : start + BATCH]) for start in range(0, len(texts), BATCH)])
    np.savez_compressed(CATALOG_VECTORS, model=MODEL, keys=[text_key(t) for t in texts], vectors=vectors)


def load_catalog_vectors(store: Store) -> None:
    """Shipped with the repo, so onboarding's map is there without embedding ~100 texts first (~40 s, and longer at
    low priority). A text changed since has no vector here; the refresh loop embeds it as usual."""
    shipped = np.load(CATALOG_VECTORS)
    if shipped["model"] != MODEL:
        return
    missing = {text_key(t) for t in catalog_texts()} - store.embedded_keys(MODEL)
    rows = zip(shipped["keys"].tolist(), shipped["vectors"])
    store.save_embeddings(MODEL, [(key, vector.tobytes()) for key, vector in rows if key in missing])


def embed_new(store: Store, embed: Embedder) -> None:
    started = time.monotonic()
    texts = pending_texts(store)  # first: they're few, and onboarding is waiting for them
    for start in range(0, len(texts), BATCH):
        batch = texts[start : start + BATCH]
        store.save_embeddings(MODEL, [(text_key(t), v.tobytes()) for t, v in zip(batch, embed(batch))])
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


def serve() -> None:
    logging.basicConfig(level=logging.INFO)
    embed = load_embedder()
    for line in sys.stdin:  # until the server closes our input
        texts = json.loads(line)
        vectors = np.vstack([embed(texts[start : start + BATCH]) for start in range(0, len(texts), BATCH)])
        print(json.dumps(vectors.tolist()), flush=True)


class LiveEmbedder:
    """The model in a child process (`serve`) that stays up while it's in use, so a text takes ~150 ms instead of a
    model load each time. It quits after IDLE_SECONDS without a request."""

    IDLE_SECONDS = 60

    def __init__(self):
        self.child: asyncio.subprocess.Process | None = None
        self.lock = asyncio.Lock()
        self.idle: asyncio.TimerHandle | None = None

    async def embed(self, texts: list[str]) -> np.ndarray:
        async with self.lock:  # one request at a time: answers come back in order on one pipe
            if self.child is None:
                self.child = await asyncio.create_subprocess_exec(
                    sys.executable,
                    "-m",
                    "app.embed",
                    "serve",
                    cwd=ROOT,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                )
            self.child.stdin.write((json.dumps(texts) + "\n").encode())
            await self.child.stdin.drain()
            line = await self.child.stdout.readline()
            if not line:
                self.child = None
                raise RuntimeError("the embedding process stopped")
            if self.idle:
                self.idle.cancel()
            self.idle = asyncio.get_running_loop().call_later(self.IDLE_SECONDS, self.stop)
            return np.array(json.loads(line), np.float32)

    def stop(self) -> None:
        if self.child and self.child.returncode is None:
            self.child.stdin.close()  # it reads to the end of its input, then exits
        self.child = None


if __name__ == "__main__":
    if sys.argv[1:] == ["serve"]:
        serve()
    elif sys.argv[1:] == ["catalog"]:
        write_catalog_vectors(load_embedder())
    else:
        main()
