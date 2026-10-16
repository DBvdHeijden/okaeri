import asyncio
import json
import logging
import os
import random
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

import numpy as np
from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import settings
from app.embed import (
    MODEL, LiveEmbedder, about_document, model_downloaded, pending, source_document, stored_vectors, text_key, topic_document,
)
from app.fetch import Refresher
from app.models import Article, Event, Source
from app.rank import learn, rank, sample, switched_on
from app.sources import (
    BY_ID, LANGUAGES, MEDIA, SOURCES, TAG_DESCRIPTIONS, TOPICS, in_tab, medium_of, source_matches, speaks, tags_for,
)
from app.store import Store, default_path, open_store

log = logging.getLogger("okaeri")

HERE = Path(__file__).parent
PAGE_SIZE = 100  # app.js splits these into viewport-sized pages
SAMPLE_SIZE = 5
TOP_SIZE = 5  # the stories onboarding shows while you tune the ranking
SOURCES_PER_INTEREST = 3  # onboarding ticks the sources nearest to each interest you wrote
MIN_MATCH = 0.65  # ...if at least this close: below it, a source isn't about it (unrelated ones mostly score 0.60-0.64)
RING_PULL = 0.78  # step 3's map: how far toward its fields a point goes, the fields being on a ring of 1
TEMPERATURE = 0.015  # how sharply a point goes to its nearest field rather than between several
HISTORY_SIZE = 100
HISTORY_VIEWS = {"opened": "Opened", "liked": "Liked", "hidden": "Hidden"}



def store() -> Store:
    return open_store(default_path())


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = None
    app.state.refresher = None
    if os.environ.get("OKAERI_FETCH", "1") != "0":
        app.state.refresher = Refresher(store(), BY_ID)
        task = asyncio.create_task(app.state.refresher.run())
    yield
    live.stop()
    if task:
        task.cancel()


live = LiveEmbedder()  # onboarding's map, while you're on it
app = FastAPI(title="okaeri", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
templates = Jinja2Templates(directory=HERE / "templates")


def static(path: str) -> str:
    # The version changes with the file, so browsers can keep it without asking (see cache_static).
    return f"/static/{path}?v={int((HERE / 'static' / path).stat().st_mtime)}"


templates.env.globals["static"] = static


@app.middleware("http")
async def cache_static(request: Request, call_next):
    # Without this Firefox re-checks the stylesheet on many page switches; when the server is busy fetching,
    # that wait outlasts its paint delay and it flashes an empty window. Fonts, linked from style.css without
    # a version, are cached too: give a changed font a new file name.
    response = await call_next(request)
    if request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return response


def same_origin(request: Request) -> bool:
    if site := request.headers.get("sec-fetch-site"):
        return site in ("same-origin", "none")
    origin = request.headers.get("origin")
    return origin is None or urlsplit(origin).netloc == request.headers.get("host")


@app.middleware("http")
async def refuse_cross_site_posts(request: Request, call_next):
    # Any website can submit a form to localhost; only our own pages may change state.
    if request.method == "POST" and not same_origin(request):
        return PlainTextResponse("Cross-site request refused", status_code=403)
    return await call_next(request)


def ago(dt: datetime) -> str:
    seconds = (datetime.now(UTC) - dt).total_seconds()
    if seconds < 60:
        return "now"
    for unit, size in (("w", 604800), ("d", 86400), ("h", 3600), ("m", 60)):
        if seconds >= size:
            return f"{int(seconds // size)}{unit}"
    return "now"


def count(n: int, word: str) -> str:
    return f"{n:,} {word}" + ("" if n == 1 else "s")


templates.env.filters["ago"] = ago
templates.env.filters["count"] = count
templates.env.globals["medium_of"] = medium_of
templates.env.globals["tags_for"] = tags_for
templates.env.globals["media"] = MEDIA
templates.env.globals["tag_descriptions"] = TAG_DESCRIPTIONS
templates.env.filters["language_name"] = LANGUAGES.get


def history(view: str) -> list[Article]:
    """Opened, liked or hidden stories, most recent first; chronological by design, so not ranked."""
    events = store().events()
    times = {
        "opened": {e.key: e.at for e in events if e.type == "click"},
        "liked": switched_on(events, "seed", "unseed"),
        "hidden": switched_on(events, "hide", "unhide"),
    }[view]
    newest = sorted(times.items(), key=lambda item: item[1], reverse=True)[:HISTORY_SIZE]
    return store().stories(dict(newest), BY_ID)  # the whole catalog: links stay for sources you no longer follow


def event_topics(events: list[Event]) -> dict[str, frozenset[str]]:
    """The topics of the stories you opened, liked or hid, for Recommended's taste per topic. From every story
    still stored: many have left the feed."""
    return {a.key: tags_for(a) for a in store().stories({e.key: e.at for e in events}, BY_ID)}


def recommended(pool: list[Article], events: list[Event]) -> list[Article]:
    return rank(pool, events, settings.load(), stored_vectors(store()), "recommended", event_topics(events))


def feed(selected: dict[str, Source], tab: dict) -> list[Article]:
    """A tab's stories, in its sort: on the homepage, and while you tune the ranking in onboarding."""
    pool = [a for a in store().articles(selected) if in_tab(a, tab)]
    events = store().events()
    return recommended(pool, events) if tab["sort"] == "recommended" else rank(pool, events, settings.load())


@app.get("/", response_class=HTMLResponse)
def home(
    request: Request,
    tab: str = "",
    n: Annotated[int, Query(ge=1)] = PAGE_SIZE,
    show: Literal["opened", "liked", "hidden"] = "opened",
):
    selected = {i: BY_ID[i] for i in settings.enabled_sources() if i in BY_ID}
    if not selected:
        return RedirectResponse("/onboarding", status_code=303)
    tabs = settings.tabs()
    active = next((t for t in tabs if t["slug"] == tab), tabs[0])  # the first tab is the default
    if active["history"]:
        ranked = history(show)
    else:
        ranked = feed(selected, active)
    return templates.TemplateResponse(
        request,
        "home.html",
        {
            "articles": ranked[:n],
            "more": len(ranked) > n,
            "n": n,
            "page_size": PAGE_SIZE,
            "tab": active,
            "tabs": tabs,
            "show": show,
            "history_views": HISTORY_VIEWS,
            "pending": store().pending(selected),
            "today": datetime.now().strftime("%A, %-d %B"),
            "name": settings.name(),
        },
    )


@app.post("/sort/{tab}")
def sort_tab(tab: str, sort: Annotated[Literal["latest", "recommended"], Form()]):
    if not settings.set_sort(tab, sort):
        raise HTTPException(404)
    return RedirectResponse(f"/?tab={tab}", status_code=303)


def background_work(request: Request) -> str:
    """What the embedding child is doing, shown in Settings; empty when nothing runs."""
    refresher = getattr(request.app.state, "refresher", None)
    if not (refresher and refresher.embedding):
        return ""
    if not model_downloaded():
        return "downloading language model (~330 MB, one time)…"
    return f"indexing articles: {len(pending(store())):,} to go"


@app.get("/progress", response_class=PlainTextResponse)
def progress(request: Request) -> str:
    return background_work(request)


def find_article(id: str) -> Article:
    # The whole catalog, so History links still work for sources no longer followed.
    if article := store().article(id, BY_ID):
        return article
    raise HTTPException(404)


@app.get("/r/{id}")
def open_article(id: str, to: str = ""):
    article = find_article(id)
    store().add_event("click", article.key)
    return RedirectResponse(article.discussion_url if to == "thread" else article.url, status_code=302)


def back(request: Request) -> RedirectResponse:
    return RedirectResponse(request.headers.get("referer", "/"), status_code=303)


@app.post("/hide/{id}")
def hide(request: Request, id: str):
    store().add_event("hide", find_article(id).key)
    return back(request)


@app.post("/unhide/{id}")
def unhide(request: Request, id: str):
    store().add_event("unhide", find_article(id).key)
    return back(request)


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    # Some browsers ask for /favicon.ico regardless of the <link> tags.
    return FileResponse(HERE / "static" / "favicon-32.png", media_type="image/png")


def wake_refresher(request: Request) -> None:
    if refresher := getattr(request.app.state, "refresher", None):
        refresher.wake.set()


# Settings: the sources you follow, and a way back into onboarding. Onboarding is only for when nothing is picked yet.

def tab_editor_context() -> dict:
    """What the tab editor (_tabs.html) needs, in Settings and the onboarding tabs step."""
    tabs = settings.all_tabs()
    # The sources you follow, plus any a tab still uses, so saving never silently drops one.
    ids = {*settings.enabled_sources(), *(s for t in tabs for s in t["sources"])}
    return {
        "tabs": tabs,
        "topics": sorted(TOPICS),
        "source_choices": sorted((BY_ID[i] for i in ids if i in BY_ID), key=lambda s: s.name.lower()),
        "max_tabs": settings.MAX_TABS,
    }


templates.env.filters["source_name"] = lambda id: BY_ID[id].name


@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    enabled = settings.enabled_sources()
    if not enabled:
        return RedirectResponse("/onboarding", status_code=303)
    groups = [
        (medium["label"], sorted((s for s in spoken_sources() if s.medium == m), key=lambda s: s.id not in enabled))
        for m, medium in MEDIA.items()
    ]
    return templates.TemplateResponse(
        request,
        "settings.html",
        {**tab_editor_context(), **ranking_context(), "groups": groups, "selected": enabled, "languages": LANGUAGES, "spoken": settings.languages(), "progress": background_work(request)},
    )


def ranking_context() -> dict:
    return {"weights": settings.weights(), "has_history": bool(store().events())}


@app.post("/settings")
def settings_submit(
    request: Request,
    sources: Annotated[list[str] | None, Form()] = None,
    languages: Annotated[list[str] | None, Form()] = None,
    tabs: Annotated[str | None, Form()] = None,  # JSON from the tab editor; absent without JS
    like: Annotated[float | None, Form()] = None,
    hidden: Annotated[float | None, Form()] = None,
    fresh: Annotated[float | None, Form()] = None,
    popular: Annotated[float | None, Form()] = None,
    surprise: Annotated[float | None, Form(alias="random")] = None,  # not `random`: that's the module
):
    # At least one language: unticking them all keeps the ones you had.
    if picked := [lang for lang in languages or [] if lang in LANGUAGES]:
        settings.set_languages(picked)
    # Sources in a language you dropped go too.
    settings.set_enabled_sources([i for i in sources or [] if i in BY_ID and speaks(BY_ID[i], settings.languages())])
    if None not in (like, hidden, fresh, popular, surprise):
        settings.set_weights({"like": like, "hidden": hidden, "fresh": fresh, "popular": popular, "random": surprise})
    if tabs is not None:
        settings.set_tabs(json.loads(tabs))
    wake_refresher(request)
    return RedirectResponse("/", status_code=303)


# Onboarding: your name (optional), the languages and media you read, what you like to read about, fields, sources,
# a sample of stories to rate, the ranking, then (optionally) tabs.

def spoken_sources() -> list[Source]:
    return [s for s in SOURCES if speaks(s, settings.languages())]


def source_count(fits) -> int:
    return sum(map(fits, spoken_sources()))


@app.post("/history/clear")
def clear_history():
    """Forget every opened, liked and hidden story, and with them everything Recommended learned."""
    store().clear_events()
    return RedirectResponse("/settings", status_code=303)


@app.post("/onboarding/redo")
def onboarding_redo():
    """Start over from Settings, as on the first run: every setting goes back to its default, and likes and
    dislikes go too. Those are taken back as events, so the log stays whole; a dislike is a hide, so stories
    hidden on the homepage come back as well. Opened stories stay."""
    settings.reset()  # otherwise old answers, like the sources you followed, prefill the new steps
    events = store().events()
    for key in switched_on(events, "seed", "unseed"):
        store().add_event("unseed", key)
    for key in switched_on(events, "hide", "unhide"):
        store().add_event("unhide", key)
    return RedirectResponse("/onboarding?redo=1", status_code=303)


@app.get("/onboarding", response_class=HTMLResponse)
def onboarding_name(request: Request, redo: bool = False):
    # Once set up, only a redo (or Back from the next step) comes here.
    if settings.enabled_sources() and not redo:
        return RedirectResponse("/settings", status_code=303)
    wake_refresher(request)  # the first time, the embedding model downloads while you're on the first steps
    return templates.TemplateResponse(request, "onboarding_name.html", {"name": settings.name()})


@app.post("/onboarding")
def onboarding_name_submit(name: Annotated[str, Form()] = ""):
    settings.set_name(name)
    return RedirectResponse("/onboarding/languages", status_code=303)


# Step 3: what you'd like to read about, in your own words, a few words each. Each becomes a point on a map of the
# fields, and the sources nearest to it come out of it. Later steps tick the fields and sources nearest to them.

@app.get("/onboarding/about", response_class=HTMLResponse)
def onboarding_about(request: Request):
    wake_refresher(request)
    return templates.TemplateResponse(
        request, "onboarding_about.html", {"about": settings.about(), "max_interests": settings.MAX_INTERESTS}
    )


@app.post("/onboarding/about")
def onboarding_about_submit(request: Request, about: Annotated[list[str] | None, Form()] = None):
    settings.set_about(about or [])
    wake_refresher(request)  # embeds any the map didn't, ready for the steps that use them
    return RedirectResponse("/onboarding/interests", status_code=303)


async def vectors_for(texts: list[str]) -> np.ndarray:
    """Their vectors, embedding (and saving) the ones not stored yet."""
    stored = await asyncio.to_thread(stored_vectors, store())
    if missing := [t for t in dict.fromkeys(texts) if text_key(t) not in stored]:
        new = await live.embed(missing)
        await asyncio.to_thread(store().save_embeddings, MODEL, [(text_key(t), v.tobytes()) for t, v in zip(missing, new)])
        stored |= {text_key(t): v for t, v in zip(missing, new)}
    return np.vstack([stored[text_key(t)] for t in texts])


def field_ring(topic_vectors: np.ndarray) -> np.ndarray:
    """The fields evenly around a circle, in the order a flat projection of them (PCA) has them, so related fields sit
    side by side. The projection itself bunches most of them in the middle."""
    centered = topic_vectors - topic_vectors.mean(axis=0)
    xy = centered @ np.linalg.svd(centered, full_matrices=False)[2][:2].T
    angles = np.empty(len(xy))
    angles[np.argsort(np.arctan2(xy[:, 1], xy[:, 0]))] = np.linspace(0, 2 * np.pi, len(xy), endpoint=False)
    return np.column_stack([np.cos(angles), np.sin(angles)])


def place(vectors: np.ndarray, topic_vectors: np.ndarray, ring: np.ndarray) -> np.ndarray:
    """Inside the ring, toward the fields each is nearest to: close to one if it's clearly about it, between several
    if it's about all of them."""
    scores = vectors @ topic_vectors.T
    weights = np.exp((scores - scores.max(axis=1, keepdims=True)) / TEMPERATURE)
    return RING_PULL * (weights / weights.sum(axis=1, keepdims=True)) @ ring


about_map: dict = {}  # made once: the catalog doesn't change while the server runs


async def make_about_map() -> dict:
    if not about_map:
        topics = sorted(TOPICS)
        vectors = await vectors_for([topic_document(t) for t in topics] + [source_document(s) for s in SOURCES])
        topic_vectors, source_vectors = vectors[: len(topics)], vectors[len(topics) :]
        ring = field_ring(topic_vectors)
        about_map.update(
            topics=topics, topic_vectors=topic_vectors, ring=ring, source_vectors=source_vectors,
            fields=[{"name": t, "x": x, "y": y} for t, (x, y) in zip(topics, ring.tolist())],
            sources=[
                {"id": s.id, "name": s.name, "description": s.description, "x": x, "y": y}
                for s, (x, y) in zip(SOURCES, place(source_vectors, topic_vectors, ring).tolist())
            ],
        )
    return about_map


def readable() -> list[int]:
    """The sources (as indexes into SOURCES) in the languages and media you read: the only ones the map brings up."""
    media = settings.interests()["media"]
    return [i for i, s in enumerate(SOURCES) if speaks(s, settings.languages()) and s.medium in media]


def waiting() -> JSONResponse:
    return JSONResponse({"waiting": True}, status_code=503)  # the model is still downloading: the page asks again


@app.get("/onboarding/about/map")
async def onboarding_about_map():
    if not model_downloaded():
        return waiting()
    m = await make_about_map()
    return {"fields": m["fields"], "sources": [m["sources"][i] for i in readable()]}


@app.post("/onboarding/about/place")
async def onboarding_about_place(text: Annotated[str, Form()]):
    """Where one of your interests goes on the map, the field it's nearest to, and the sources nearest to it."""
    if not model_downloaded():
        return waiting()
    m = await make_about_map()
    vector = (await vectors_for([about_document(text.strip()[:100])]))[0]
    (x, y), = place(vector[None], m["topic_vectors"], m["ring"]).tolist()
    candidates = readable()
    closeness = m["source_vectors"][candidates] @ vector
    nearest_sources = [i for i in np.argsort(-closeness)[:SOURCES_PER_INTEREST] if closeness[i] >= MIN_MATCH]
    return {
        "x": x, "y": y,
        "field": m["topics"][int(np.argmax(m["topic_vectors"] @ vector))],
        "sources": [SOURCES[candidates[i]].id for i in nearest_sources],
    }


def about_scores(documents: dict[str, str]) -> dict[str, np.ndarray]:
    """For each of `documents` (id -> text): how close it is to each interest you wrote in step 3, in order. Empty if
    you wrote none, or none is embedded yet: then the steps that use them work as without."""
    vectors = stored_vectors(store())
    interests = [vectors[key] for a in settings.about() if (key := text_key(about_document(a))) in vectors]
    if not interests:
        return {}
    return {i: np.array([v @ vectors[text_key(d)] for v in interests]) for i, d in documents.items() if text_key(d) in vectors}


def nearest_each(scores: dict[str, np.ndarray], k: int, floor: float = -1) -> list[str]:
    """The k ids nearest to each interest in turn, at least `floor` close, without repeats."""
    interests = len(next(iter(scores.values()), []))
    by_interest = (sorted(scores, key=lambda i: scores[i][n], reverse=True)[:k] for n in range(interests))
    return list(dict.fromkeys(i for n, ids in enumerate(by_interest) for i in ids if scores[i][n] >= floor))


@app.get("/onboarding/languages", response_class=HTMLResponse)
def onboarding_languages(request: Request):
    return reading_page(request, {*settings.languages(), *settings.interests()["media"]})


def reading_page(request: Request, chosen: set[str], missing: str = "", status_code: int = 200) -> HTMLResponse:
    """Step 2: how you like to read, before what about, so the next step only brings up sources you'll get."""
    groups = [
        ("Languages", "languages", [(code, name, "", sum(s.language == code for s in SOURCES)) for code, name in LANGUAGES.items()]),
        ("Media", "media", [(m, medium["label"], medium["description"], sum(s.medium == m for s in SOURCES)) for m, medium in MEDIA.items()]),
    ]
    return templates.TemplateResponse(
        request, "onboarding_languages.html", {"groups": groups, "chosen": chosen, "missing": missing}, status_code=status_code
    )


@app.post("/onboarding/languages")
def onboarding_languages_submit(
    request: Request, languages: Annotated[list[str] | None, Form()] = None, media: Annotated[list[str] | None, Form()] = None
):
    languages = [lang for lang in languages or [] if lang in LANGUAGES]
    media = [m for m in media or [] if m in MEDIA]
    if not languages or not media:
        # The same step again, with your picks and what's missing. 422: Turbo only shows a failed form's page.
        missing = " and ".join(word for word, picked in (("one language", languages), ("one medium", media)) if not picked)
        return reading_page(request, {*languages, *media}, f"Pick at least {missing}.", 422)
    settings.set_languages(languages)
    settings.set_interests(media, settings.interests()["topics"])
    return RedirectResponse("/onboarding/about", status_code=303)


def interests_page(
    request: Request, chosen: set[str], missing: str = "", status_code: int = 200, suggested: bool = False
) -> HTMLResponse:
    # Counted among the sources in the languages and media you read: what each field would actually bring.
    media = settings.interests()["media"]
    counts = [(t, source_count(lambda s: t in s.tags and s.medium in media)) for t in sorted(TOPICS)]
    groups = [("Fields", "topics", [(t, t, TAG_DESCRIPTIONS[t], n) for t, n in counts])]
    return templates.TemplateResponse(
        request, "onboarding_interests.html", {"groups": groups, "chosen": chosen, "missing": missing, "suggested": suggested},
        status_code=status_code,
    )


@app.get("/onboarding/interests", response_class=HTMLResponse)
def onboarding_interests(request: Request):
    interests = settings.interests()
    # The first time through, each interest you wrote ticks the field nearest to it.
    suggested = [] if interests["topics"] else nearest_each(about_scores({t: topic_document(t) for t in TOPICS}), 1)
    return interests_page(request, {*interests["topics"], *suggested}, suggested=bool(suggested))


@app.post("/onboarding/interests")
def onboarding_interests_submit(request: Request, topics: Annotated[list[str] | None, Form()] = None):
    topics = [t for t in topics or [] if t in TOPICS]
    if not topics:
        # The same step again, with what's missing. 422: Turbo only shows a failed form's page.
        return interests_page(request, set(), "Pick at least one field.", 422)
    settings.set_interests(settings.interests()["media"], topics)
    settings.start_tabs(topics)  # step 8 opens with them
    return RedirectResponse("/onboarding/sources", status_code=303)


@app.get("/onboarding/sources", response_class=HTMLResponse)
def onboarding_sources(request: Request):
    interests = settings.interests()
    # Only sources in a medium you picked and in one of your fields (or in none, like Hacker News): onboarding stays
    # short, and Settings has them all.
    offered = [s for s in spoken_sources() if source_matches(s, interests["media"], interests["topics"])]
    # A fold per field you picked, as in the step before; each source once, under the first of yours it covers.
    groups: dict[str, list[Source]] = {t: [] for t in interests["topics"]} | {"general": []}
    for s in offered:
        groups[next((t for t in interests["topics"] if t in s.tags), "general")].append(s)
    groups = {label: sources for label, sources in groups.items() if sources}
    # The first time through, each interest you wrote ticks the sources nearest to it, and each fold its best one;
    # in each fold, the nearest (to any of your interests) first. Without interests, all start ticked.
    selected, suggested = settings.enabled_sources(), False
    if not selected and (scores := about_scores({s.id: source_document(s) for s in offered})):
        # A source added to the catalog since may have no vector yet: it goes last, unticked.
        groups = {
            label: sorted(sources, key=lambda s: scores[s.id].max() if s.id in scores else -1, reverse=True)
            for label, sources in groups.items()
        }
        best_per_fold = [sources[0].id for sources in groups.values() if sources[0].id in scores]
        selected = list(dict.fromkeys(nearest_each(scores, SOURCES_PER_INTEREST, MIN_MATCH) + best_per_fold))
        suggested = True
    selected = selected or [s.id for s in offered]
    groups = {label: sorted(sources, key=lambda s: s.id not in selected) for label, sources in groups.items()}
    return templates.TemplateResponse(
        request, "onboarding_sources.html", {"groups": list(groups.items()), "selected": selected, "suggested": suggested}
    )


@app.post("/onboarding/sources")
def onboarding_sources_submit(request: Request, sources: Annotated[list[str] | None, Form()] = None):
    chosen = [i for i in sources or [] if i in BY_ID]
    settings.set_enabled_sources(chosen)
    log.info("selected %d sources", len(chosen))
    wake_refresher(request)
    return RedirectResponse("/onboarding/sample", status_code=303)


def sample_pool(shuffle: bool = False, field: str = "") -> list[Article]:
    """Stories from your sources that fit your interests (and the field, if one is picked) and that you haven't
    rated yet: best first by the weights learned so far (which Surprise keeps from narrowing too fast), or
    shuffled, to explore."""
    selected = {i: BY_ID[i] for i in settings.enabled_sources() if i in BY_ID}
    interests = settings.interests()
    pool = [
        a for a in store().articles(selected)
        if any(source_matches(BY_ID[s], interests["media"], interests["topics"]) for s in a.source_ids)
        and (not field or field in tags_for(a))
    ]
    events = store().events()
    rated = switched_on(events, "seed", "unseed") | switched_on(events, "hide", "unhide")
    # Each interest you wrote in step 3 counts as one more like here (only here: they're not saved as likes), so the
    # first stories to rate are the ones nearest to one of them. rank() skips a like it has no vector for yet.
    now = datetime.now(UTC)
    events = [*events, *(Event("seed", text_key(about_document(a)), now) for a in settings.about())]
    ranked = rank(pool, events, settings.load()) if shuffle else recommended(pool, events)
    unrated = [a for a in ranked if a.key not in rated]
    if shuffle:
        random.shuffle(unrated)
    return unrated


@app.get("/onboarding/sample", response_class=HTMLResponse)
def onboarding_sample(request: Request, shuffle: bool = False, field: str = ""):
    """Stories to rate, picked by what your ratings taught so far; "Show others" shuffles instead. Picking one of
    your fields rates just that one, so each gets rated, not only the one with the most stories."""
    selected = [i for i in settings.enabled_sources() if i in BY_ID]
    events = store().events()
    rated = switched_on(events, "seed", "unseed") | switched_on(events, "hide", "unhide")
    rated_topics = [tags_for(a) for a in store().stories(rated, BY_ID)]
    return templates.TemplateResponse(
        request,
        "onboarding_sample.html",
        {
            "articles": sample(sample_pool(shuffle, field), SAMPLE_SIZE),
            "field": field,
            "fields": [(t, sum(t in topics for topics in rated_topics)) for t in settings.interests()["topics"]],
            "pending": store().pending(selected),
            "liked": len(switched_on(events, "seed", "unseed")),
            "disliked": len(switched_on(events, "hide", "unhide")),
        },
    )


@app.get("/onboarding/sample/next", response_class=HTMLResponse)
def onboarding_sample_next(request: Request, shown: str = "", sources: str = "", field: str = ""):
    """One new story to replace one you just rated: the best match so far in the same field, not on screen yet,
    and from a source not on screen if possible."""
    pool = [a for a in sample_pool(field=field) if a.id not in shown.split(",")]
    if not pool:
        return Response(status_code=204)
    fresh = [a for a in pool if a.source_id not in sources.split(",")] or pool
    return templates.TemplateResponse(request, "_sample_row.html", {"a": fresh[0]})


def top_stories(field: str = "") -> list[Article]:
    """What All would show first, by Recommended, with the weights as they are now; or just one field's stories.
    The same weights either way: a field only narrows what you see."""
    selected = {i: BY_ID[i] for i in settings.enabled_sources() if i in BY_ID}
    tab = {**settings.ALL_TAB, "sort": "recommended", "topics": [field] if field else []}
    return feed(selected, tab)[:TOP_SIZE]


@app.get("/onboarding/tune", response_class=HTMLResponse)
def onboarding_tune(request: Request, field: str = ""):
    return templates.TemplateResponse(
        request,
        "onboarding_tune.html",
        {"articles": top_stories(field), "weights": settings.weights(), "field": field, "fields": settings.interests()["topics"]},
    )


@app.get("/onboarding/tune/top", response_class=HTMLResponse)
def onboarding_tune_top(request: Request, field: str = ""):
    """The top stories again, after you moved a dial."""
    rows = templates.get_template("_sample_row.html")
    return HTMLResponse("".join(rows.render(a=a, preview=True) for a in top_stories(field)))


@app.post("/onboarding/weights")
def onboarding_weights_submit(
    name: Annotated[Literal["like", "hidden", "fresh", "popular", "random"], Form()], value: Annotated[float, Form()]
):
    """A dial you moved while tuning. Rate more stories afterwards (Back) and it keeps learning, but stays this
    far from what's learned."""
    learned = learned_weights()
    if name in learned:
        settings.set_weight_nudges(settings.weight_nudges() | {name: value - learned[name]})
    settings.set_weights(settings.weights() | {name: value})
    return Response(status_code=204)


@app.get("/onboarding/tabs", response_class=HTMLResponse)
def onboarding_tabs(request: Request):
    return templates.TemplateResponse(request, "onboarding_tabs.html", tab_editor_context())


@app.post("/onboarding/tabs")
def onboarding_tabs_submit(tabs: Annotated[str | None, Form()] = None):  # JSON from the tab editor; absent without JS
    if tabs is not None:
        settings.set_tabs(json.loads(tabs))
    return RedirectResponse("/", status_code=303)


@app.post("/onboarding/rate/{id}")
def onboarding_rate(request: Request, id: str, rating: Annotated[Literal["up", "down", "none"], Form()]):
    """A rating, and the weights learned again from all of them. Only here: afterwards the weights are yours."""
    response = rate(request, id, rating)
    nudges = settings.weight_nudges()
    learned = {k: min(max(v + nudges.get(k, 0), 0), 1) for k, v in learned_weights().items()}
    settings.set_weights(settings.weights() | learned)
    return response


def learned_weights() -> dict[str, float]:
    """The weights your onboarding ratings teach, before any nudges of yours."""
    events = store().events()
    stories = {a.key: a for a in store().articles(BY_ID)}  # with their real publish times, for freshness
    liked = [stories[k] for k in switched_on(events, "seed", "unseed") if k in stories]
    disliked = [stories[k] for k in switched_on(events, "hide", "unhide") if k in stories]
    return learn(liked, disliked, stored_vectors(store()))


@app.post("/rate/{id}")
def rate(request: Request, id: str, rating: Annotated[Literal["up", "down", "none"], Form()]):
    """A like is a seed, a dislike a hide (so it also leaves the feed); "none" takes back either."""
    key = find_article(id).key
    events = store().events()
    liked, hidden = key in switched_on(events, "seed", "unseed"), key in switched_on(events, "hide", "unhide")
    if liked and rating != "up":
        store().add_event("unseed", key)
    if hidden and rating != "down":
        store().add_event("unhide", key)
    if rating == "up" and not liked:
        store().add_event("seed", key)
    if rating == "down" and not hidden:
        store().add_event("hide", key)
    return back(request)

