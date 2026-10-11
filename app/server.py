import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import settings
from app.fetch import Refresher
from app.models import Article
from app.rank import rank, sample
from app.sources import BY_ID, FORMATS, SOURCES, TOPICS, format_of, in_tab, source_format, source_matches
from app.store import Store, default_path, open_store

log = logging.getLogger("okaeri")

HERE = Path(__file__).parent
PAGE_SIZE = 100  # app.js splits these into viewport-sized pages
SAMPLE_SIZE = 20

ALL = ("all", "All")  # always the first tab
HISTORY = ("history", "History")  # always the last tab, aligned right
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


@app.get("/", response_class=HTMLResponse)
def home(request: Request, tab: str = "all", n: Annotated[int, Query(ge=1)] = PAGE_SIZE):
    selected = {i: BY_ID[i] for i in settings.enabled_sources() if i in BY_ID}
    if not selected:
        return RedirectResponse("/onboarding", status_code=303)
    user_tabs = settings.tabs()
    active = next((t for t in user_tabs if t["slug"] == tab), None)
    if tab == "history":
        ranked = store().history(BY_ID)  # chronological by design; not a recommendation, so not ranked
    else:
        tab = active["slug"] if active else "all"
        pool = store().articles(selected)
        if active:
            pool = [a for a in pool if in_tab(a, active["tags"])]
        ranked = rank(pool, store().events(), settings.load())
    return templates.TemplateResponse(
        request,
        "home.html",
        {
            "articles": ranked[:n],
            "more": len(ranked) > n,
            "n": n,
            "page_size": PAGE_SIZE,
            "tab": tab,
            "tabs": [ALL, *((t["slug"], t["name"]) for t in user_tabs), HISTORY],
            "pending": store().pending(selected),
            "today": datetime.now().strftime("%A, %-d %B"),
        },
    )


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


# Onboarding, also the settings page: interests, then sources, then a sample of stories to seed ranking.

def source_count(tag: str) -> int:
    return sum(tag in s.tags for s in SOURCES)


@app.get("/onboarding", response_class=HTMLResponse)
def onboarding_interests(request: Request):
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
    if refresher := getattr(request.app.state, "refresher", None):
        refresher.wake.set()
    return RedirectResponse("/onboarding/sample", status_code=303)


@app.get("/onboarding/sample", response_class=HTMLResponse)
def onboarding_sample(request: Request):
    selected = {i: BY_ID[i] for i in settings.enabled_sources() if i in BY_ID}
    interests = settings.interests()
    pool = [a for a in store().articles(selected) if in_tab(a, [*interests["formats"], *interests["topics"]])]
    events = store().events()
    seeded = {e.key for e in events if e.type == "seed"}
    return templates.TemplateResponse(
        request,
        "onboarding_sample.html",
        {
            "articles": sample(rank(pool, events, settings.load()), SAMPLE_SIZE),
            "seeded": seeded,
            "pending": store().pending(selected),
        },
    )


@app.post("/onboarding/sample")
def onboarding_sample_submit(articles: Annotated[list[str] | None, Form()] = None):
    seeded = {e.key for e in store().events() if e.type == "seed"}
    for id in articles or []:
        if (article := store().article(id, BY_ID)) and article.key not in seeded:
            store().add_event("seed", article.key)
    return RedirectResponse("/", status_code=303)

