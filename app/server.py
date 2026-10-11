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

from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import settings
from app.embed import model_downloaded, pending, stored_vectors
from app.fetch import Refresher
from app.models import Article
from app.rank import rank, sample, switched_on
from app.sources import BY_ID, FORMATS, SOURCES, TOPICS, format_of, in_tab, source_format, source_matches
from app.store import Store, default_path, open_store

log = logging.getLogger("okaeri")

HERE = Path(__file__).parent
PAGE_SIZE = 100  # app.js splits these into viewport-sized pages
SAMPLE_SIZE = 5
HISTORY_SIZE = 100
HISTORY_VIEWS = {"opened": "Opened", "liked": "Liked", "hidden": "Hidden"}

FORMAT_GROUPS = {"paper": "Papers", "blog": "Blogs", "forum": "Forums", "news": "News"}  # onboarding sections


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
    if task:
        task.cancel()


app = FastAPI(title="okaeri", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
templates = Jinja2Templates(directory=HERE / "templates")


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
templates.env.globals["format_of"] = format_of


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
        pool = [a for a in store().articles(selected) if in_tab(a, active["tags"], active["sources"])]
        vectors = stored_vectors(store()) if active["sort"] == "recommended" else None
        ranked = rank(pool, store().events(), settings.load(), vectors, active["sort"])
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
        },
    )


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
    """What the tab editor (_tabs.html) needs, in Settings and onboarding step 4."""
    tabs = settings.all_tabs()
    # The sources you follow, plus any a tab still uses, so saving never silently drops one.
    ids = {*settings.enabled_sources(), *(s for t in tabs for s in t["sources"])}
    return {
        "tabs": tabs,
        "formats": list(FORMAT_GROUPS),
        "topics": sorted(TOPICS),
        "source_choices": sorted((BY_ID[i] for i in ids if i in BY_ID), key=lambda s: s.name.lower()),
        "max_tabs": settings.MAX_TABS,
    }


templates.env.filters["source_name"] = lambda id: BY_ID[id].name
templates.env.globals["source_format"] = source_format


@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    enabled = settings.enabled_sources()
    if not enabled:
        return RedirectResponse("/onboarding", status_code=303)
    groups = [
        (label, sorted((s for s in SOURCES if source_format(s) == f), key=lambda s: s.id not in enabled))
        for f, label in FORMAT_GROUPS.items()
    ]
    return templates.TemplateResponse(
        request,
        "settings.html",
        {**tab_editor_context(), "groups": groups, "selected": enabled, "progress": background_work(request)},
    )


@app.post("/settings")
def settings_submit(
    request: Request,
    sources: Annotated[list[str] | None, Form()] = None,
    tabs: Annotated[str | None, Form()] = None,  # JSON from the tab editor; absent without JS
):
    settings.set_enabled_sources([i for i in sources or [] if i in BY_ID])
    if tabs is not None:
        settings.set_tabs(json.loads(tabs))
    wake_refresher(request)
    return RedirectResponse("/", status_code=303)


# Onboarding: interests, then sources, then a sample of stories to rate, then (optionally) tabs.

def source_count(tag: str) -> int:
    return sum(tag in s.tags for s in SOURCES)


@app.get("/onboarding", response_class=HTMLResponse)
def onboarding_interests(request: Request, redo: bool = False):
    # A redo starts from your current answers; nothing changes until you submit each step.
    if settings.enabled_sources() and not redo:
        return RedirectResponse("/settings", status_code=303)
    groups = [
        ("Fields", "topics", [(t, t, source_count(t)) for t in sorted(TOPICS)]),
        ("Formats", "formats", [(f, label, source_count(f)) for f, label in FORMAT_GROUPS.items()]),
    ]
    interests = settings.interests()
    chosen = {*interests["formats"], *interests["topics"]}
    return templates.TemplateResponse(request, "onboarding_interests.html", {"groups": groups, "chosen": chosen})


@app.post("/onboarding")
def onboarding_interests_submit(
    formats: Annotated[list[str] | None, Form()] = None, topics: Annotated[list[str] | None, Form()] = None
):
    settings.set_interests([f for f in formats or [] if f in FORMATS], [t for t in topics or [] if t in TOPICS])
    return RedirectResponse("/onboarding/sources", status_code=303)


@app.get("/onboarding/sources", response_class=HTMLResponse)
def onboarding_sources(request: Request):
    interests = settings.interests()
    matching = [s for s in SOURCES if source_matches(s, interests["formats"], interests["topics"])]
    groups = [(label, [s for s in matching if source_format(s) == f]) for f, label in FORMAT_GROUPS.items()]
    groups.append(("Other sources", [s for s in SOURCES if s not in matching]))
    # First time through, everything that matches starts checked.
    selected = settings.enabled_sources() or [s.id for s in matching]
    return templates.TemplateResponse(
        request, "onboarding_sources.html", {"groups": [g for g in groups if g[1]], "selected": selected}
    )


@app.post("/onboarding/sources")
def onboarding_sources_submit(request: Request, sources: Annotated[list[str] | None, Form()] = None):
    chosen = [i for i in sources or [] if i in BY_ID]
    settings.set_enabled_sources(chosen)
    log.info("selected %d sources", len(chosen))
    wake_refresher(request)
    return RedirectResponse("/onboarding/sample", status_code=303)


@app.get("/onboarding/sample", response_class=HTMLResponse)
def onboarding_sample(request: Request):
    selected = {i: BY_ID[i] for i in settings.enabled_sources() if i in BY_ID}
    interests = settings.interests()
    pool = [
        a for a in store().articles(selected)
        if any(source_matches(BY_ID[s], interests["formats"], interests["topics"]) for s in a.source_ids)
    ]
    events = store().events()
    rated = switched_on(events, "seed", "unseed") | switched_on(events, "hide", "unhide")
    unrated = [a for a in rank(pool, events, settings.load()) if a.key not in rated]
    random.shuffle(unrated)  # a different few on every load: that's the "show others" button
    return templates.TemplateResponse(
        request,
        "onboarding_sample.html",
        {"articles": sample(unrated, SAMPLE_SIZE), "pending": store().pending(selected)},
    )


@app.get("/onboarding/tabs", response_class=HTMLResponse)
def onboarding_tabs(request: Request):
    return templates.TemplateResponse(request, "onboarding_tabs.html", tab_editor_context())


@app.post("/onboarding/tabs")
def onboarding_tabs_submit(tabs: Annotated[str | None, Form()] = None):  # JSON from the tab editor; absent without JS
    if tabs is not None:
        settings.set_tabs(json.loads(tabs))
    return RedirectResponse("/", status_code=303)


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

