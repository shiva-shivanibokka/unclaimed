"""Think ahead: a decision takes ~0.5 s, longer than a voice turn should wait. Decisions are
cached by the exact household, and after each one the likely next households (every
question just asked answered "no"/"none", or the main one answered "yes") are computed in
the background while the person is still talking. Exact answers like "$1,450 rent" miss
the cache and are computed on demand. When the interview stops, the results are what's
asked for next, so they are computed ahead the same way.

Guesses never come first: a guess starts only when no real request is waiting, and only
for the latest request (older guesses are dropped). A real request can still wait for a
guess already running (one decision at most); /next reports that wait.
"""

import itertools
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from .batch import apply
from .calculate import calculate
from .dictionary import load
from .household import Household
from .interview import conditional_on_declined, next_question

CACHE_SIZE = 512  # households; a decision is a few KB
_cache: OrderedDict[str, dict] = OrderedDict()
_cache_lock = threading.Lock()
_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="think-ahead")
_latest = itertools.count()  # request number; guesses for older requests are dropped
_newest = 0
_waiting = 0  # real requests waiting for or holding the engine
_state = threading.Lock()


def _key(h: Household, kind: str = "next") -> str:
    # The screening date decides the rules (e.g. the SNAP year starts Oct 1), so an
    # unset date is keyed by today's.
    return kind + h.model_dump_json() + (h.as_of or date.today()).isoformat()


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


def results(h: Household) -> dict:
    """What /calculate returns: the results, and the programs that depend on a declined
    answer (the results screen says "if ...")."""
    return {**calculate(h), "conditional": conditional_on_declined(h)}


def _compute(key: str, work, h: Household, compute_lock: threading.Lock) -> tuple[dict, bool, float]:
    """(value, served from cache, seconds waited for the engine)."""
    global _waiting
    cached, waited = _get(key), 0.0
    if cached is not None:
        return cached, True, waited
    with _state:
        _waiting += 1
    try:
        t = time.perf_counter()
        with compute_lock:
            waited = time.perf_counter() - t
            value = work(h)
    finally:
        with _state:
            _waiting -= 1
    _put(key, value)
    return value, False, waited


def decide(h: Household, compute_lock: threading.Lock) -> tuple[dict, bool, float]:
    """(decision, served from cache, seconds waited for the engine). Queues think-ahead for
    the likely next households, or for the results once the interview stops."""
    global _newest
    decision, hit, waited = _compute(_key(h), next_question, h, compute_lock)
    with _state:
        _newest = request = next(_latest)
    guesses = [(_key(n), next_question, n) for n in likely_next(h, decision)]
    if decision["stop"]:
        guesses = [(_key(h, "results"), results, h)]
    for guess in guesses:
        _pool.submit(_prefetch, *guess, compute_lock, request)
    return decision, hit, waited


def calculate_results(h: Household, compute_lock: threading.Lock) -> tuple[dict, bool, float]:
    """results(h), from the cache when think-ahead already computed it."""
    return _compute(_key(h, "results"), results, h, compute_lock)


def _prefetch(key: str, work, h: Household, compute_lock: threading.Lock, request: int) -> None:
    with _state:
        if request != _newest or _waiting:
            return  # stale, or a person is waiting: never make them wait behind a guess
    if _get(key) is not None or not compute_lock.acquire(blocking=False):
        return
    try:
        value = work(h)
    finally:
        compute_lock.release()
    _put(key, value)
