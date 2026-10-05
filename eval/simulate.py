"""Simulated interviews: an oracle that knows a household's full truth answers whatever the
Question Engine asks. The result where the interview stops is compared with the
full-information result (every question answered).

A case is a dict: state, county and/or zip, people (id, relationship, age, plus any
answers), household (household answers), declines (keys the person won't answer, e.g.
"a.immigration_status"). With a zip, the interview starts from the ZIP alone and the
oracle answers "which county?" with the case's county. Anything the truth doesn't specify
is answered with the question's low what-if (0, no, renter, citizen; 1 year in the US and
0 work quarters), so only answers a case sets away from that can catch a skipped question.

Compared per program and, for programs decided person by person (Medicaid, CHIP, WIC),
per person ("medicaid:b").
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))

from unclaimed_engine.batch import PERSON_SEP, apply  # noqa: E402
from unclaimed_engine.calculate import calculate  # noqa: E402
from unclaimed_engine.dictionary import load  # noqa: E402
from unclaimed_engine.household import Household  # noqa: E402
from unclaimed_engine.interview import _applies, conditional_on_declined, next_question  # noqa: E402

STRUCTURE = ("id", "relationship", "age")
MAX_TURNS = 60  # safety net for the simulation only; the interview itself has no cap


def _truth(case: dict) -> dict:
    """(person id or None, question id) -> true answer, for every question."""
    d = load()
    given = {(p["id"], k): v for p in case["people"] for k, v in p.items() if k not in STRUCTURE}
    given |= {(None, k): v for k, v in case.get("household", {}).items()}
    out = {}
    for q in d.questions:
        owners = [p["id"] for p in case["people"]] if q.entity == "person" else [None]
        for pid in owners:
            out[(pid, q.id)] = given.get((pid, q.id), q.what_if[0])
    return out


def _start(case: dict) -> Household:
    """What the interview starts from: where (the ZIP alone when there is one) and who."""
    return Household(state=case["state"], county=None if case.get("zip") else case.get("county"),
                     zip=case.get("zip"), as_of=case.get("as_of"),
                     people=[{k: p[k] for k in STRUCTURE} for p in case["people"]])


def _check(case: dict, full: Household) -> None:
    """A case may only give answers to questions that apply to that person: anything else
    describes a household that can't exist (e.g. Social Security retirement at 50)."""
    people = {p.id: p for p in full.people}
    for p in case["people"]:
        for k in p.keys() - set(STRUCTURE):
            if not _applies(load().question(k), full, people[p["id"]]):
                raise ValueError(f"{case['id']}: {k} does not apply to {p['id']}")


def run(case: dict, decide=next_question, on_turn=None, max_turns: int = MAX_TURNS) -> dict:
    """Interview `case` with `decide` (the Question Engine, or a policy to compare it with:
    eval/experiments.py), calling on_turn(h, decision) before each answer. First the short
    interview (core questions, then results with "maybe"s: `quick`); then, as if the person
    asked to check every "maybe", until none is left (the top-level results)."""
    truth = _truth(case)
    full = apply(_start(case).model_copy(update={"county": case.get("county")}), truth)
    _check(case, full)
    declines = set(case.get("declines", []))
    ids = [p["id"] for p in case["people"]]
    want = _programs(calculate(full), ids)
    h = _start(case)
    turns, latencies, questions, quick, maybe = [], [], 0, None, set()
    while len(turns) < max_turns:
        t = time.perf_counter()
        d = decide(h)
        latencies.append((time.perf_counter() - t) * 1000)
        if on_turn:
            on_turn(h, d)
        if d["stop"]:
            maybe = set(d.get("unanswered", {}))
            if quick is None:
                quick = {"turns": len(turns), "questions": questions, **_outcome(h, want, ids, maybe)}
            if maybe <= set(h.focus):
                break
            h = h.model_copy(update={"focus": sorted(set(h.focus) | maybe)})  # "check the maybes"
            continue
        turns.append(d["ask"]["question"])
        questions += 1 + len(d["together"])  # a group asked in one breath counts each question
        if d["ask"]["question"] == "county":
            h = h.model_copy(update={"county": case["county"]})
            continue
        keys = [(x["person"], x["question"]) for x in [d["ask"], *d["together"]]]
        answers = {k: truth[k] for k in keys if _label(k) not in declines}
        refused = [_label(k) for k in keys if _label(k) in declines]
        h = apply(h, answers).model_copy(update={"declined": [*h.declined, *refused]})
    return {
        "id": case["id"], "turns": len(turns), "questions": questions, "asked": turns, "hit_turn_cap": len(turns) >= max_turns,
        "decision_ms": latencies, **_outcome(h, want, ids, maybe), "quick": quick,
        "programs_total": len(want), "eligible_truth": sorted(p for p in want if want[p][0]),
    }


def _outcome(h: Household, want: dict, ids: list[str], maybe: set[str]) -> dict:
    """The results at this point against the full-information ones. Programs shown as "if ..."
    (an unasked question could flip them: `maybe`; or they depend on a declined answer) are
    never a false "you qualify"; a program shown as "maybe" isn't missed."""
    got = _programs(calculate(h), ids)
    conditional = set(conditional_on_declined(h))
    base = lambda p: p.split(PERSON_SEP)[0]  # noqa: E731
    return {
        "false_qualify": sorted(p for p in want if got[p][0] and not want[p][0] and base(p) not in conditional | maybe),
        "conditional": sorted(conditional),
        "maybe": sorted(maybe),
        "missed": sorted(p for p in want if want[p][0] and not got[p][0] and base(p) not in maybe),
        "amount_error": round(sum(abs(got[p][1] - want[p][1]) for p in want if got[p][0] and want[p][0]), 2),
    }


def _label(key) -> str:
    pid, qid = key
    return qid if pid is None else f"{pid}.{qid}"


def _programs(result: dict, ids: list[str]) -> dict[str, tuple[bool, float]]:
    """program -> (eligible, monthly dollars), plus "program:person" -> (eligible, 0) for
    programs decided person by person. Coverage programs (no `amount`: their engine value
    is the cost of coverage) count for eligibility only."""
    out = {}
    for p in result["programs"]:
        out[p["id"]] = (p["eligible"], p["monthly_value"] if "amount" in p else 0.0)
        if "eligible_people" in p:
            for pid in ids:
                out[f"{p['id']}{PERSON_SEP}{pid}"] = (pid in p["eligible_people"], 0.0)
    return out
