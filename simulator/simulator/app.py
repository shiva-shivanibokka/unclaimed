"""The Unclaimed Alexa+ simulator: serves the Echo Show-style page and one endpoint per
spoken turn. Public and free for judges, so every turn is rate limited (Bedrock costs money).

Run: uvicorn simulator.app:app --port 8090
"""

import json
import logging
import threading
import time
from collections import defaultdict, deque
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import agent, speech
from .settings import setting

log = logging.getLogger("unclaimed.simulator")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

STATIC = Path(__file__).parent / "static"
TURNS_PER_IP_PER_HOUR = int(setting("TURNS_PER_IP_PER_HOUR"))
FULL_RATE_TOKENS_PER_DAY = int(setting("FULL_RATE_TOKENS_PER_DAY"))
POLLY_CHARS_PER_DAY = int(setting("POLLY_CHARS_PER_DAY"))
MAX_TEXT = 600  # characters per spoken turn
MAX_MESSAGES = 160  # conversation length; a long screening is well under this
# The history is resent (and billed) every turn; a long screening's is about a third of this.
MAX_HISTORY_BYTES = 150_000
ALLOWED_BLOCKS = {"text", "toolUse", "toolResult"}

app = FastAPI(title="Unclaimed Alexa+ simulator", version="0.1.0")
app.mount("/static", StaticFiles(directory=STATIC), name="static")

_hits: dict[str, deque] = defaultdict(deque)
_day: list = [time.strftime("%Y-%m-%d"), 0, 0]  # date, full-rate tokens used, characters spoken
_limits = threading.Lock()


def _client_ip(request: Request) -> str:
    # Behind the AWS load balancer the client is the last X-Forwarded-For entry (the one the
    # balancer added); earlier entries are whatever the client sent.
    forwarded = request.headers.get("x-forwarded-for")
    return forwarded.rsplit(",", 1)[-1].strip() if forwarded else (request.client.host if request.client else "?")


def _admit(ip: str) -> None:
    now = time.time()
    with _limits:
        today = time.strftime("%Y-%m-%d")
        if _day[0] != today:
            _day[:] = [today, 0, 0]
        if _day[1] >= FULL_RATE_TOKENS_PER_DAY:
            raise HTTPException(429, "The demo has reached today's limit. Please try again tomorrow.")
        hits = _hits[ip]
        while hits and hits[0] < now - 3600:
            hits.popleft()
        if len(hits) >= TURNS_PER_IP_PER_HOUR:
            raise HTTPException(429, "That's a lot of turns for one hour. Please try again a bit later.")
        hits.append(now)


def _spent(tokens: dict) -> None:
    with _limits:
        _day[1] += tokens["input"] + tokens["cache_write"] + tokens["output"]


def _may_speak(text: str) -> bool:
    """Count the reply against the day's Polly characters; False once they're used up."""
    with _limits:
        if _day[2] + len(text) > POLLY_CHARS_PER_DAY:
            return False
        _day[2] += len(text)
        return True


class Turn(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_TEXT)
    messages: list[dict] = Field(default_factory=list, max_length=MAX_MESSAGES)


def _check_history(messages: list[dict]) -> None:
    """The conversation comes back from the browser: accept only plain text and tool turns."""
    if len(json.dumps(messages)) > MAX_HISTORY_BYTES:
        raise HTTPException(413, "The conversation is too long; start a new one.")
    for m in messages:
        if m.get("role") not in ("user", "assistant") or not isinstance(m.get("content"), list):
            raise HTTPException(422, "bad conversation history")
        for block in m["content"]:
            if not isinstance(block, dict) or not set(block) <= ALLOWED_BLOCKS:
                raise HTTPException(422, "bad conversation history")


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


@app.post("/api/turn")
def turn(body: Turn, request: Request) -> dict:
    _admit(_client_ip(request))
    _check_history(body.messages)
    try:
        out = agent.turn(body.messages, body.text)
    except Exception as e:
        log.error("turn failed: %s", type(e).__name__)  # never the conversation itself
        raise HTTPException(503, "Alexa couldn't answer just now. Please try again.") from e
    _spent(out["tokens"])
    out["reply"] = speech.plain(out["reply"])
    # base64 MP3 clips, one per sentence; None: the page uses the browser's voice
    out["audio"] = speech.audio(out["reply"]) if _may_speak(out["reply"]) else None
    log.info("turn ms=%d tools_ms=%d model_calls=%d in_tokens=%d out_tokens=%d", out["timing"]["total_ms"],
             out["timing"]["tools_ms"], out["timing"]["model_calls"], out["tokens"]["input"], out["tokens"]["output"])
    return out
