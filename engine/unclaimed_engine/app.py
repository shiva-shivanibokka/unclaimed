"""HTTP API for the engine. Run: uvicorn unclaimed_engine.app:app --port 8000"""

import logging
import threading
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .calculate import calculate
from .household import Household

log = logging.getLogger("unclaimed.engine")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# PolicyEngine's tax-benefit system (and its parameter caches) is shared, process-wide
# state that isn't documented as thread-safe, so calculations run one at a time.
_lock = threading.Lock()
_ready = False

WARMUP = [
    Household(state=s, county=c, people=[
        {"id": "a", "relationship": "head", "age": 35, "employment_income": 20_000},
        {"id": "c", "relationship": "child", "age": 3},
    ])
    for s, c in (("CA", "LOS_ANGELES_COUNTY_CA"), ("IL", "COOK_COUNTY_IL"))
]


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Cold start is ~20 s plus a few seconds per program on first use: pay it before
    # taking traffic instead of on a person's first question.
    global _ready
    t = time.perf_counter()
    for h in WARMUP:
        calculate(h)
    _ready = True
    log.info("warm in %.1f s", time.perf_counter() - t)
    yield


app = FastAPI(title="Unclaimed engine", version="0.1.0", lifespan=lifespan)


@app.get("/health")
def health() -> dict:
    return {"ok": True, "ready": _ready}


@app.post("/calculate")
def calculate_endpoint(household: Household) -> dict:
    t = time.perf_counter()
    with _lock:
        result = calculate(household)
    ms = round((time.perf_counter() - t) * 1000)
    # Anonymous metrics only: never log the household itself.
    log.info("calculate state=%s people=%d ms=%d", household.state, len(household.people), ms)
    return {**result, "ms": ms}
