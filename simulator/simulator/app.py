"""The Unclaimed Alexa+ simulator: serves the Echo Show-style page, the MCP server's screens,
and the live voice conversation (live.py). Public and free for judges, so conversations are
rate limited there (Bedrock costs money).

Run: uvicorn simulator.app:app --port 8090
"""

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import agent, live

log = logging.getLogger("unclaimed.simulator")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

STATIC = Path(__file__).parent / "static"

app = FastAPI(title="Unclaimed Alexa+ simulator", version="0.2.0")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.middleware("http")
async def revalidate(request: Request, call_next):
    """The page and its files are checked for a newer version on every load (unchanged ones
    come back as a quick "not modified"), so a deploy never leaves a browser running an old
    script against a new page."""
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


def client_ip(headers, client) -> str:
    # Behind the AWS load balancer the client is the last X-Forwarded-For entry (the one the
    # balancer added); earlier entries are whatever the client sent.
    forwarded = headers.get("x-forwarded-for")
    return forwarded.rsplit(",", 1)[-1].strip() if forwarded else (client.host if client else "?")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.get("/api/screens")
def screens() -> dict:
    """The MCP server's screens, for the page to host (MCP Apps)."""
    try:
        return agent.screens()
    except Exception as e:
        log.error("screens failed: %s", type(e).__name__)
        raise HTTPException(503, "The screen isn't available just now.") from e


@app.websocket("/api/live")
async def live_conversation(ws: WebSocket) -> None:
    await live.serve(ws, client_ip(ws.headers, ws.client))
