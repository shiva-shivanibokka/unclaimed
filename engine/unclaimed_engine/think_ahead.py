"""Think ahead: a decision takes ~0.5 s, longer than a voice turn should wait. Decisions are
cached by the exact household, and after each one the likely next households (every
question just asked answered "no"/"none", or the main one answered "yes") are computed in
the background while the person is still talking. Exact answers like "$1,450 rent" miss
the cache and are computed on demand.
"""

import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

from .batch import apply
from .dictionary import load
from .household import Household
from .interview import next_question

CACHE_SIZE = 512  # households; a decision is a few KB
_cache: OrderedDict[str, dict] = OrderedDict()
_cache_lock = threading.Lock()
_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="think-ahead")


def _key(h: Household) -> str:
    return h.model_dump_json()


def _get(key: str) -> dict | None:
    with _cache_lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
    return None


def _put(key: str, decision: dict) -> None:
    with _cache_lock:
        _cache[key] = decision
        _cache.move_to_end(key)
        while len(_cache) > CACHE_SIZE:
            _cache.popitem(last=False)


def likely_next(h: Household, decision: dict) -> list[Household]:
    """Households after the most likely answers: all asked questions at their low what-if
    value ("no"/"none"), and the main question at its high value."""
    if decision["stop"]:
        return []
    d = load()
    asked = [decision["ask"], *decision["together"]]
    low = {(x["person"], x["question"]): d.question(x["question"]).what_if[0] for x in asked}
    main = (decision["ask"]["person"], decision["ask"]["question"])
    high = {**low, main: d.question(main[1]).what_if[1]}
    return [apply(h, low), apply(h, high)]


def decide(h: Household, compute_lock: threading.Lock) -> tuple[dict, bool]:
    """(decision, served from cache). Queues think-ahead for the likely next households."""
    key = _key(h)
    cached = _get(key)
    if cached is None:
        with compute_lock:
            cached = next_question(h)
        _put(key, cached)
        hit = False
    else:
        hit = True
    for nxt in likely_next(h, cached):
        _pool.submit(_prefetch, nxt, compute_lock)
    return cached, hit


def _prefetch(h: Household, compute_lock: threading.Lock) -> None:
    key = _key(h)
    if _get(key) is not None:
        return
    # Never make a person wait behind a guess: skip if a real request holds the engine.
    if not compute_lock.acquire(blocking=False):
        return
    try:
        decision = next_question(h)
    finally:
        compute_lock.release()
    _put(key, decision)
