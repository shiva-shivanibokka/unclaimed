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


def run(case: dict) -> dict:
    truth = _truth(case)
    full = apply(_start(case).model_copy(update={"county": case.get("county")}), truth)
    _check(case, full)
    declines = set(case.get("declines", []))
    h = _start(case)
    turns, latencies = [], []
    while len(turns) < MAX_TURNS:
        t = time.perf_counter()
        d = next_question(h)
        latencies.append((time.perf_counter() - t) * 1000)
        if d["stop"]:
            break
        turns.append(d["ask"]["question"])
        if d["ask"]["question"] == "county":
            h = h.model_copy(update={"county": case["county"]})
            continue
        keys = [(x["person"], x["question"]) for x in [d["ask"], *d["together"]]]
        answers = {k: truth[k] for k in keys if _label(k) not in declines}
        refused = [_label(k) for k in keys if _label(k) in declines]
        h = apply(h, answers).model_copy(update={"declined": [*h.declined, *refused]})
    ids = [p.id for p in h.people]
    got, want = _programs(calculate(h), ids), _programs(calculate(full), ids)
    # Programs that depend on a declined answer are reported as "if ...", not "you qualify".
    conditional = set(conditional_on_declined(h))
    return {
        "id": case["id"], "turns": len(turns), "asked": turns, "hit_turn_cap": len(turns) >= MAX_TURNS,
        "decision_ms": latencies,
        "false_qualify": sorted(p for p in want if got[p][0] and not want[p][0]
                                and p.split(PERSON_SEP)[0] not in conditional),
        "conditional": sorted(conditional),
        "missed": sorted(p for p in want if want[p][0] and not got[p][0]),
        "amount_error": round(sum(abs(got[p][1] - want[p][1]) for p in want if got[p][0] and want[p][0]), 2),
        "programs_total": len(want), "eligible_truth": sorted(p for p in want if want[p][0]),
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
