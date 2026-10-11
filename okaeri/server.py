import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import uvicorn
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from okaeri import mock
from okaeri.rank import rank

log = logging.getLogger("okaeri")

HERE = Path(__file__).parent
MAX_ARTICLES = 100  # the client splits these into viewport-sized pages

TABS = [("all", "All"), ("paper", "Papers"), ("blog", "Blogs"), ("forum", "Forums"), ("news", "News")]
KIND_LABELS = {"paper": "Papers", "blog": "Blogs", "forum": "Forums", "news": "News"}

app = FastAPI(title="okaeri")
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
templates = Jinja2Templates(directory=HERE / "templates")


def ago(dt: datetime) -> str:
    seconds = (datetime.now(UTC) - dt).total_seconds()
    if seconds < 60:
        return "now"
    for unit, size in (("w", 604800), ("d", 86400), ("h", 3600), ("m", 60)):
        if seconds >= size:
            return f"{int(seconds // size)}{unit}"
    return "now"


templates.env.filters["ago"] = ago


@app.get("/", response_class=HTMLResponse)
def home(request: Request, kind: str = "all"):
    if kind not in mock.KINDS:
        kind = "all"
    pool = [a for a in mock.articles() if kind == "all" or a.kind == kind]
    ranked = rank(pool)
    return templates.TemplateResponse(
        request,
        "home.html",
        {
            "articles": ranked[:MAX_ARTICLES],
            "kind": kind,
            "tabs": TABS,
            "today": datetime.now().strftime("%A, %-d %B"),
        },
    )


@app.get("/onboarding", response_class=HTMLResponse)
def onboarding(request: Request):
    groups = [(KIND_LABELS[k], [s for s in mock.SOURCES if s.kind == k]) for k in mock.KINDS]
    return templates.TemplateResponse(request, "onboarding.html", {"groups": groups})


@app.post("/onboarding")
def onboarding_submit(sources: Annotated[list[str] | None, Form()] = None):
    # No persistence yet; this becomes the settings write later.
    log.info("onboarding selected sources: %s", sources or [])
    return RedirectResponse("/", status_code=303)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(
        "okaeri.server:app",
        host="127.0.0.1",
        port=int(os.environ.get("OKAERI_PORT", "8000")),
        reload=os.environ.get("OKAERI_RELOAD") == "1",
        workers=1,
    )
