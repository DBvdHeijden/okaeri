import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import FastAPI, Form, Request
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.fetch import Refresher
from app.models import KIND_LABELS, KINDS
from app.rank import rank
from app.sources import BY_ID, SOURCES
from app.store import Store, default_path, open_store

log = logging.getLogger("okaeri")

HERE = Path(__file__).parent
MAX_ARTICLES = 100  # the client splits these into viewport-sized pages

TABS = [("all", "All"), *KIND_LABELS.items()]
HISTORY = ("history", "History")  # always the last tab, aligned right



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


@app.get("/", response_class=HTMLResponse)
def home(request: Request, kind: str = "all"):
    selected = {i: BY_ID[i] for i in store().selected() if i in BY_ID}
    if not selected:
        return RedirectResponse("/onboarding", status_code=303)
    # Only offer tabs for kinds the user follows; one kind needs no tabs at all.
    kinds = {s.kind for s in selected.values()}
    tabs = [(value, label) for value, label in TABS if value == "all" or value in kinds]
    if len(tabs) <= 2:
        tabs = tabs[:1]
    tabs.append(HISTORY)
    if kind not in kinds and kind != "history":
        kind = "all"
    if kind == "history":
        ranked = store().history()  # chronological by design; not a recommendation, so not ranked
    else:
        pool = [a for a in store().articles(selected) if kind == "all" or a.kind == kind]
        ranked = rank(pool)
    return templates.TemplateResponse(
        request,
        "home.html",
        {
            "articles": ranked[:MAX_ARTICLES],
            "kind": kind,
            "tabs": tabs,
            "pending": store().pending(selected),
            "today": datetime.now().strftime("%A, %-d %B"),
        },
    )


@app.post("/api/clicks", status_code=204)
def record_click(
    key: Annotated[str, Form()],
    url: Annotated[str, Form()],
    title: Annotated[str, Form()],
    source: Annotated[str, Form()],
    kind: Annotated[str, Form()],
):
    if kind in KINDS:
        store().record_click(key, url, title[:300], source[:100], kind)


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    # Some browsers ask for /favicon.ico regardless of the <link> tags.
    return FileResponse(HERE / "static" / "favicon-32.png", media_type="image/png")


@app.get("/onboarding", response_class=HTMLResponse)
def onboarding(request: Request):
    groups = [(KIND_LABELS[k], [s for s in SOURCES if s.kind == k]) for k in KINDS]
    return templates.TemplateResponse(
        request, "onboarding.html", {"groups": groups, "selected": store().selected()}
    )


@app.post("/onboarding")
def onboarding_submit(request: Request, sources: Annotated[list[str] | None, Form()] = None):
    chosen = [i for i in sources or [] if i in BY_ID]
    store().set_selected(chosen)
    log.info("selected %d sources", len(chosen))
    if refresher := getattr(request.app.state, "refresher", None):
        refresher.wake.set()
    return RedirectResponse("/", status_code=303)

