"""HTTP API for the engine. Run: uvicorn unclaimed_engine.app:app --port 8000"""

import logging
import os
import threading
import time
from contextlib import asynccontextmanager
from dataclasses import asdict

from fastapi import FastAPI, HTTPException, Path as PathParam
from pydantic import BaseModel, Field

from . import think_ahead
from .calculate import calculate
from .dictionary import load
from .geo import locate
from .gross_up import gross_from_take_home
from .household import MAX_MONEY, Household
from .interview import conditional_on_declined
from .programs import PROGRAMS, SUPPORTED_STATES

log = logging.getLogger("unclaimed.engine")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# PolicyEngine's tax-benefit system (and its parameter caches) is shared, process-wide
# state that isn't documented as thread-safe, so calculations run one at a time.
_lock = threading.Lock()
# Requests allowed in flight (running + waiting). Beyond it we answer 503 at once
# instead of queueing: a ~0.5 s calculation behind a long queue is useless to a voice turn.
MAX_IN_FLIGHT = int(os.environ.get("UNCLAIMED_MAX_IN_FLIGHT", "8"))
_slots = threading.BoundedSemaphore(MAX_IN_FLIGHT)
_ready = False

WARMUP = [
    Household(state=s, people=[
        {"id": "a", "relationship": "head", "age": 35, "employment_income": 20_000},
        {"id": "c", "relationship": "child", "age": 3},
    ])
    for s in SUPPORTED_STATES
]


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Pay the cold start (see engine/README.md for measured times) before taking
    # traffic instead of on a person's first question.
    global _ready
    t = time.perf_counter()
    for h in WARMUP:
        calculate(h)
    _ready = True
    log.info("warm in %.1f s", time.perf_counter() - t)
    yield


app = FastAPI(title="Unclaimed engine", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict:
    # async: runs on the event loop, so it answers even when every worker thread is busy.
    return {"ok": True, "ready": _ready}


@app.get("/programs")
def programs() -> list[dict]:
    """The one program list: the MCP server, simulator and plan cards read it from here."""
    return [{"id": p.id, "name": p.name, "state_names": dict(p.state_names), "per": p.per,
             "states": list(p.states), "coverage": p.coverage} for p in PROGRAMS]


@app.get("/dictionary")
def dictionary() -> dict:
    """The questions we can ask (the Question Engine and MCP server read them from here),
    with enum options resolved from the engine, and the assumption statements."""
    d = load()
    return {
        "questions": [asdict(q) | ({"options": list(q.options)} if q.answer["type"] == "enum" else {})
                      for q in d.questions],
        "statements": [g.statement for g in d.assumed if g.statement],
        "structure": d.structure,
    }


@app.get("/zip/{zip_code}")
def zip_lookup(zip_code: str = PathParam(pattern=r"^\d{5}$")) -> dict:
    """Which supported states (and counties) a ZIP is in, from the HUD crosswalk: the MCP
    server asks here instead of carrying its own ZIP data."""
    return {"zip": zip_code, "states": locate(zip_code, SUPPORTED_STATES)}


class GrossUp(BaseModel):
    household: Household
    person: str
    question: str = Field(description="A question whose answer is pay before taxes (answer.basis: before_tax)")
    take_home: float = Field(gt=0, le=MAX_MONEY, description="Take-home pay, USD per year")


@app.post("/gross_up")
def gross_up_endpoint(req: GrossUp) -> dict:
    """Pay before taxes that leaves the given take-home pay, with PolicyEngine's tax rules."""
    q = next((q for q in load().questions if q.id == req.question), None)
    if not q or q.answer.get("basis") != "before_tax":
        raise HTTPException(status_code=422, detail=f"{req.question} is not asked as pay before taxes")
    if req.person not in {p.id for p in req.household.people}:
        raise HTTPException(status_code=422, detail=f"no person {req.person}")

    def work():
        t = time.perf_counter()
        with _lock:
            waited = time.perf_counter() - t
            return {"gross": round(gross_from_take_home(req.household, req.person, req.take_home, req.question), 2)}, waited
    result, ms, wait_ms = _run("gross_up", req.household, work)
    return {**result, "ms": ms, "wait_ms": wait_ms}


def _run(name: str, household: Household, work) -> tuple[dict, int, int]:
    """Bounded, timed engine work with our error handling: (result, ms, wait_ms)."""
    if not _slots.acquire(blocking=False):
        raise HTTPException(status_code=503, detail="busy, retry shortly")
    try:
        t = time.perf_counter()
        result, waited = work()
        compute = time.perf_counter() - t - waited
    except ValueError as e:  # our own validation, e.g. a ZIP with no residents in the state
        raise HTTPException(status_code=422, detail=str(e)) from e
    except Exception as e:  # engine failure: log the type only, never the household
        log.error("%s failed: %s", name, type(e).__name__)
        raise HTTPException(status_code=503, detail="calculation unavailable") from e
    finally:
        _slots.release()
    ms, wait_ms = round(compute * 1000), round(waited * 1000)
    # Anonymous metrics only: never log the household itself.
    log.info("%s state=%s people=%d ms=%d wait_ms=%d", name, household.state, len(household.people), ms, wait_ms)
    return result, ms, wait_ms


@app.post("/calculate")
def calculate_endpoint(household: Household) -> dict:
    def work():
        t = time.perf_counter()
        with _lock:
            waited = time.perf_counter() - t
            # Programs that depend on a declined answer: the results screen says "if ...".
            return {**calculate(household), "conditional": conditional_on_declined(household)}, waited
    result, ms, wait_ms = _run("calculate", household, work)
    return {**result, "ms": ms, "wait_ms": wait_ms}


@app.post("/next")
def next_endpoint(household: Household) -> dict:
    """The next question to ask (with the ones to ask in the same breath), or stop.
    Cached and computed ahead for likely answers (think_ahead.py)."""
    hit = False

    def work():
        nonlocal hit
        decision, hit, waited = think_ahead.decide(household, _lock)
        return decision, waited
    result, ms, wait_ms = _run("next", household, work)
    return {**result, "ms": ms, "wait_ms": wait_ms, "cached": hit}
