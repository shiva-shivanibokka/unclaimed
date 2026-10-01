"""The benefits interview: turns the dictionary into Question Engine candidates and asks
the engine (batched) which unknown fact would change the result the most.

Order: the core questions first (always relevant), then whatever the Question Engine
scores highest, until no remaining question would flip an eligibility or move a benefit
by at least STOP_BELOW a month.
"""

from typing import Any

import question_engine as qe

from . import batch
from .calculate import resolve_county_for
from .dictionary import Question, load
from .household import Household
from .programs import PROGRAMS

# Our tuning, defined once. A flip (qualify <-> not) outweighs this many dollars a month,
# so eligibility changes always beat amount changes of ordinary size.
FLIP_WEIGHT = 1_000
# Stop when no candidate flips anything and none moves a benefit by this much a month.
STOP_BELOW = 25
# After this many questions (a group asked together counts once), offer "estimate now".
ESTIMATE_OFFER_AFTER = 10

DICTIONARY = load()
COVERAGE = {p.id for p in PROGRAMS if p.coverage}


def _value(h: Household, pid: str | None, qid: str):
    owner = h if pid is None else next(p for p in h.people if p.id == pid)
    return getattr(owner, qid)


def _key(pid: str | None, qid: str) -> str:
    return qid if pid is None else f"{pid}.{qid}"


def _applies(q: Question, h: Household, person=None) -> bool:
    w = q.applies_when
    if "states" in w and h.state not in w["states"]:
        return False
    if person is not None:
        if "age_min" in w and person.age < w["age_min"]:
            return False
        if "age_max" in w and person.age > w["age_max"]:
            return False
        if w.get("non_citizen") and person.immigration_status in (None, "CITIZEN"):
            return False
        return True
    return True


def _requirements_met(q: Question, h: Household, pid: str | None) -> bool:
    """Prerequisites answered as required. A declined prerequisite counts as met: if
    "rent or own?" is declined, still ask the rent ("if you rent")."""
    for rid, allowed in q.requires.items():
        r = DICTIONARY.question(rid)
        rpid = pid if r.entity == "person" else None
        if _key(rpid, rid) in h.declined:
            continue
        value = _value(h, rpid, rid)
        if value is None or (allowed is None and not value) or (allowed is not None and value not in allowed):
            return False
    return True


def open_questions(h: Household) -> list[tuple[str | None, Question]]:
    """(person id or None, question) pairs that are unanswered, not declined, apply to this
    household and have their prerequisites answered; in dictionary order."""
    declined = set(h.declined)
    out = []
    for q in DICTIONARY.questions:
        owners = [(p.id, p) for p in h.people] if q.entity == "person" else [(None, None)]
        for pid, person in owners:
            if (_value(h, pid, q.id) is None and _key(pid, q.id) not in declined
                    and _applies(q, h, person) and _requirements_met(q, h, pid)):
                out.append((pid, q))
    return out


class _Calculator:
    """Question Engine calculator over the batched benefits engine. Coverage programs
    (Medicaid, CHIP) count only as flips: their engine value is the cost of coverage."""

    def evaluate(self, h: Household, changes) -> list[dict[str, tuple[bool, float]]]:
        results = batch.evaluate(h, [dict(c) for c in changes])
        return [{pid: (ok, 0.0 if pid in COVERAGE else value) for pid, (ok, value) in r.items()} for r in results]


def _candidate(h: Household, pid: str | None, q: Question, open_keys: set) -> qe.Candidate:
    """Asked once for the whole household ("does anyone have a disability?", "does anyone
    get Social Security?"): `together` holds the same question for everyone else it's open
    for, plus every open question in its group."""
    group = {q.id} | {o.id for o in DICTIONARY.questions if q.group and o.group == q.group}
    together = tuple(_single(p, DICTIONARY.question(t)) for p, t in
                     sorted((k for k in open_keys if k[1] in group and k != (pid, q.id)), key=str))
    return qe.Candidate(key=(pid, q.id), low=q.what_if[0], high=q.what_if[1], cost=q.cost, together=together)


def _single(pid: str | None, q: Question) -> qe.Candidate:
    return qe.Candidate(key=(pid, q.id), low=q.what_if[0], high=q.what_if[1], cost=q.cost)


def _view_key(c: qe.Candidate) -> tuple[str | None, Question]:
    pid, qid = c.key
    return pid, DICTIONARY.question(qid)


def _asked_count(h: Household) -> int:
    """Questions already answered or declined, a group counting once per person."""
    seen = set()
    for q in DICTIONARY.questions:
        owners = [p.id for p in h.people] if q.entity == "person" else [None]
        for pid in owners:
            if _value(h, pid, q.id) is not None or _key(pid, q.id) in h.declined:
                seen.add((pid, q.group or q.id))
    return len(seen)


def _question_view(pid: str | None, q: Question) -> dict[str, Any]:
    view = {"question": q.id, "person": pid, "definition": q.definition, "ask": q.ask,
            "answer": q.answer, "clarifiers": list(q.clarifiers), "group": q.group}
    return {**view, "options": list(q.options)} if q.answer["type"] == "enum" else view


def _possible_answers(q: Question) -> tuple:
    """Every option of a multiple choice (an immigration status other than the two extremes
    can decide a program), else the what-if values."""
    return q.options if q.answer["type"] == "enum" else tuple(q.what_if)


def conditional_on_declined(h: Household) -> dict[str, list[str]]:
    """Programs whose eligibility, for the household or any one person, depends on a
    declined answer: program -> declined keys. The result must say "if ...", never a flat
    "you qualify" (e.g. federal credits when immigration status is declined)."""
    keys = []
    for item in h.declined:
        pid, _, qid = item.rpartition(".")
        keys.append((pid or None, qid))
    if not keys:
        return {}
    variants = [(k, v) for k in keys for v in _possible_answers(DICTIONARY.question(k[1]))]
    results = batch.evaluate(h, [{k: v} for k, v in variants])
    out: dict[str, list[str]] = {}
    for k in keys:
        rows = [r for (key, _), r in zip(variants, results) if key == k]
        for outcome in rows[0]:
            if len({r[outcome][0] for r in rows}) > 1:
                program = outcome.split(batch.PERSON_SEP)[0]
                if _key(*k) not in out.get(program, []):
                    out.setdefault(program, []).append(_key(*k))
    return out


def _county_question(h: Household) -> dict | None:
    """The ZIP is split between counties (or there's no location): ask before anything
    else, since every what-if would otherwise run in the engine's default county."""
    county, candidates = resolve_county_for(h)
    if county:
        return None
    field = "county" if candidates else "zip"
    view = {"question": field, "person": None, **DICTIONARY.structure[field], "clarifiers": []}
    if candidates:
        return {**view, "answer": {"type": "enum"}, "options": candidates}
    return {**view, "answer": {"type": "text"}}


def next_question(h: Household) -> dict:
    """What to ask next (with the questions to ask in the same breath), or stop."""
    if location := _county_question(h):
        return {"stop": False, "core": True, "ask": location, "together": [], "asked": _asked_count(h),
                "offer_estimate": False}
    open_ = open_questions(h)
    open_keys = {(pid, q.id) for pid, q in open_}
    asked = _asked_count(h)
    core = [(pid, q) for pid, q in open_ if q.core]
    if core:
        pid, q = core[0]
        c = _candidate(h, pid, q, open_keys)
        return {"stop": False, "core": True, "ask": _question_view(pid, q),
                "together": [_question_view(*_view_key(t)) for t in c.together],
                "asked": asked, "offer_estimate": False}
    candidates = [_candidate(h, pid, q, open_keys) for pid, q in open_]
    decision = qe.decide(h, candidates, _Calculator(), flip_weight=FLIP_WEIGHT, stop_below=STOP_BELOW)
    why = [{"question": s.candidate.key[1], "person": s.candidate.key[0], "flips": list(s.flips),
            "swing_per_month": round(s.swing, 2), "score": round(s.score, 2)} for s in decision.ranked[:5]]
    if decision.stop:
        return {"stop": True, "core": False, "ask": None, "together": [], "asked": asked,
                "offer_estimate": False, "top_candidates": why, "conditional": conditional_on_declined(h)}
    pid, qid = decision.ask.key
    return {"stop": False, "core": False, "ask": _question_view(pid, DICTIONARY.question(qid)),
            "together": [_question_view(*_view_key(t)) for t in decision.ask.together],
            "asked": asked, "offer_estimate": asked >= ESTIMATE_OFFER_AFTER, "top_candidates": why,
            "unanswered": _depends_on_unanswered(decision.ranked)}


def _depends_on_unanswered(ranked) -> dict[str, list[str]]:
    """Programs whose eligibility, for the household or any one person, could still change
    with a question not asked yet: program -> question keys. An estimate given now must
    say "if ...", never a flat "you qualify" (the engine reads a missing answer as 0/no)."""
    out: dict[str, list[str]] = {}
    for s in ranked:
        for outcome in s.flips:
            keys = out.setdefault(outcome.split(batch.PERSON_SEP)[0], [])
            if _key(*s.candidate.key) not in keys:
                keys.append(_key(*s.candidate.key))
    return out
