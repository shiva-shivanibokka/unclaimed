"""Tier B: generated households.

1. Pairwise coverage: every pair of values across the dimensions below appears together in
   at least one household (greedy all-pairs, deterministic).
2. Every cutoff +/- $1: for each base shape, the exact earnings at which each program's
   eligibility flips (found with batched sweeps), and a household $1 on each side.
"""

import itertools
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from unclaimed_engine import batch  # noqa: E402
from unclaimed_engine.dictionary import load  # noqa: E402
from unclaimed_engine.interview import _applies  # noqa: E402

import simulate  # noqa: E402

SEED = 2026
SHAPES = {
    "single": [("head", 30)],
    "parent_1kid": [("head", 29), ("child", 3)],
    "parent_3kids": [("head", 35), ("child", 1), ("child", 7), ("child", 13)],
    "couple_2kids": [("head", 38), ("spouse", 36), ("child", 5), ("child", 10)],
    "senior": [("head", 70)],
    "senior_couple": [("head", 72), ("spouse", 68)],
    "parent_student": [("head", 50), ("child", 20)],
}
DIMENSIONS = {
    "where": [("CA", "LOS_ANGELES_COUNTY_CA"), ("CA", "ALAMEDA_COUNTY_CA"), ("CA", "FRESNO_COUNTY_CA"),
              ("CA", "MODOC_COUNTY_CA"), ("IL", "COOK_COUNTY_IL"), ("IL", "CHAMPAIGN_COUNTY_IL"), ("IL", "ADAMS_COUNTY_IL")],
    "shape": list(SHAPES),
    "earnings": [0, 12_000, 25_000, 40_000, 65_000],
    "housing": ["renter", "owner"],
    "status": ["CITIZEN", "LEGAL_PERMANENT_RESIDENT", "UNDOCUMENTED"],
    "hours": [0, 20, 40],
    "childcare": [0, 8_000, 24_000],
    "savings": [0, 15_000],
    "other_income": [None, "social_security_retirement", "unemployment_compensation", "child_support_received"],
    "disabled": [False, True],
    # Values above the what-if highs, mixed-status and disabled spouses, declined answers,
    # pregnancy and utilities: what an early stop is most likely to get wrong.
    "deduction": [None, ("child_support_paid", 15_000), ("medical_expenses", 12_000)],
    "spouse": ["same", "UNDOCUMENTED", "disabled"],
    "declines": [None, "p1.immigration_status", "housing_tenure"],
    "pregnant": [False, True],
    "utilities": [False, True],
}


def _case(cid: str, v: dict) -> dict:
    state, county = v["where"]
    people = []
    for n, (rel, age) in enumerate(SHAPES[v["shape"]]):
        p = {"id": f"p{n}", "relationship": rel, "age": age}
        if rel != "child":
            p["immigration_status"] = v["status"]
        if rel == "spouse" and v["spouse"] != "same":
            p |= {"is_disabled": True} if v["spouse"] == "disabled" else {"immigration_status": v["spouse"]}
        if p.get("immigration_status", "CITIZEN") != "CITIZEN":
            p |= {"years_in_us": 3, "work_quarters": 12}
        if n == 0:
            p |= {"employment_income": v["earnings"], "weekly_hours_worked": v["hours"] if v["earnings"] else 0,
                  "is_disabled": v["disabled"], "is_pregnant": v["pregnant"]}
            if v["other_income"]:
                p[v["other_income"]] = 6_000
            if v["deduction"]:
                p[v["deduction"][0]] = v["deduction"][1]
        if rel == "child" and age >= 18:
            p |= {"is_full_time_college_student": True, "employment_income": 5_000, "weekly_hours_worked": 10}
        people.append(p)
    household = {"savings": v["savings"]}
    household |= ({"rent": 14_400} if v["housing"] == "renter"
                  else {"housing_tenure": "OWNER_WITH_MORTGAGE", "mortgage_payments": 12_000, "property_taxes": 3_000})
    if any(rel == "child" and age < 13 for rel, age in SHAPES[v["shape"]]):
        household["childcare_expenses"] = v["childcare"]
    if v["utilities"]:
        household |= {"heating_type": "NATURAL_GAS", "electricity_bill": 2_400, "gas_bill": 1_200, "phone_bill": 600}
    case = {"id": cid, "state": state, "county": county, "people": _possible(state, county, people),
            "household": household}
    if v["declines"] and _declinable(case, v["declines"]):
        case["declines"] = [v["declines"]]
    return case


def _possible(state: str, county: str, people: list[dict]) -> list[dict]:
    """Only the answers that can exist for each person, per the dictionary's applies_when
    (no Social Security retirement at 30, no pregnancy at 70): anything else describes a
    household that can't happen."""
    full = batch.apply(simulate._start({"state": state, "county": county, "people": people}),
                       {(p["id"], k): x for p in people for k, x in p.items() if k not in simulate.STRUCTURE})
    by_id = {p.id: p for p in full.people}
    return [{k: x for k, x in p.items()
             if k in simulate.STRUCTURE or _applies(load().question(k), full, by_id[p["id"]])} for p in people]


def _declinable(case: dict, key: str) -> bool:
    pid, _, qid = key.rpartition(".")
    return not pid or any(p["id"] == pid for p in case["people"])


def pairwise() -> list[dict]:
    """Greedy all-pairs over DIMENSIONS: keep adding the random candidate that covers the
    most uncovered value pairs until every pair is covered."""
    rng = random.Random(SEED)
    names = list(DIMENSIONS)
    uncovered = {((a, x), (b, y)) for a, b in itertools.combinations(names, 2)
                 for x in range(len(DIMENSIONS[a])) for y in range(len(DIMENSIONS[b]))}
    rows = []
    while uncovered:
        best, gain = None, -1
        for _ in range(60):
            row = {n: rng.randrange(len(DIMENSIONS[n])) for n in names}
            g = sum(((a, row[a]), (b, row[b])) in uncovered for a, b in itertools.combinations(names, 2))
            if g > gain:
                best, gain = row, g
        uncovered -= {((a, best[a]), (b, best[b])) for a, b in itertools.combinations(names, 2)}
        rows.append(best)
    return [_case(f"pair-{i:03d}", {n: DIMENSIONS[n][r[n]] for n in names}) for i, r in enumerate(rows)]


def _eligibility(full, incomes: list[float]) -> list[dict]:
    head = full.people[0].id
    return [{p: ok for p, (ok, _) in r.items()}
            for r in batch.evaluate(full, [{(head, "employment_income"): x} for x in incomes])]


def cutoffs(step: int = 500, top: int = 120_000) -> list[dict]:
    """Households $1 below and above every earnings level where a program's eligibility flips."""
    out = []
    for (state, county), shape in itertools.product([("CA", "LOS_ANGELES_COUNTY_CA"), ("IL", "COOK_COUNTY_IL")], SHAPES):
        base = {"where": (state, county), "shape": shape, "earnings": 0, "housing": "renter", "status": "CITIZEN",
                "hours": 40, "childcare": 0, "savings": 0, "other_income": None, "disabled": False,
                "deduction": None, "spouse": "same", "declines": None, "pregnant": False, "utilities": False}
        case = _case("probe", base)
        full = batch.apply(simulate._start(case), simulate._truth(case))
        grid = list(range(0, top + 1, step))
        coarse = _eligibility(full, grid)
        for program in coarse[0]:
            for i in range(1, len(grid)):
                if coarse[i][program] != coarse[i - 1][program]:
                    lo = grid[i - 1]
                    fine = _eligibility(full, list(range(lo, lo + step + 1)))
                    flip = next(lo + j for j in range(1, len(fine)) if fine[j][program] != fine[j - 1][program])
                    for side, income in (("below", flip - 1), ("at", flip)):
                        out.append(_case(f"cut-{state}-{shape}-{program}-{flip}-{side}",
                                         {**base, "earnings": income}))
    return out


def cases() -> list[dict]:
    return pairwise() + cutoffs()
