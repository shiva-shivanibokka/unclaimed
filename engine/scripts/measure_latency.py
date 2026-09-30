"""Warm latency of the engine: whole-household screening and per-program cost.

Run: uv run python scripts/measure_latency.py
"""

import statistics
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from policyengine_us import Simulation  # noqa: E402

from unclaimed_engine.calculate import build_situation, calculate, period_for, periods  # noqa: E402
from unclaimed_engine.household import Household  # noqa: E402
from unclaimed_engine.programs import PROGRAMS  # noqa: E402


def hh(state, county, *people, **kw):
    return Household(state=state, county=county, people=list(people), **kw)  # as_of = today


def p(i, rel, age, inc=0, **kw):
    return {"id": i, "relationship": rel, "age": age, "employment_income": inc, **kw}


SHAPES = {
    "CA single adult, $18k": hh("CA", "LOS_ANGELES_COUNTY_CA", p("a", "head", 30, 18_000, weekly_hours_worked=30)),
    "CA parent + 2 kids, $32k, rent": hh("CA", "LOS_ANGELES_COUNTY_CA", p("a", "head", 34, 32_000), p("b", "child", 4), p("c", "child", 9), rent=21_600),
    "CA couple + baby, $48k, child care": hh("CA", "FRESNO_COUNTY_CA", p("a", "head", 29, 48_000), p("b", "spouse", 28), p("c", "child", 1), childcare_expenses=9_000),
    "IL senior, $14k": hh("IL", "COOK_COUNTY_IL", p("a", "head", 70, 0, self_employment_income=14_000)),
    "IL couple + 3 kids, $60k": hh("IL", "COOK_COUNTY_IL", p("a", "head", 40, 60_000), p("b", "spouse", 38), p("c", "child", 6), p("d", "child", 11), p("e", "child", 15)),
    "IL pregnant, $0": hh("IL", "PEORIA_COUNTY_IL", p("a", "head", 24, 0, is_pregnant=True)),
}


def ms(t):
    return (time.perf_counter() - t) * 1000


def main(reps: int = 5) -> None:
    t = time.perf_counter()
    for h in SHAPES.values():  # warm-up: cold start + first calculation of each program
        calculate(h)
    print(f"warm-up: {ms(t) / 1000:.1f} s\n")

    print(f"{'household (full screening, warm)':40s} {'median':>8s} {'max':>8s}")
    for name, h in SHAPES.items():
        runs = []
        for _ in range(reps):
            t = time.perf_counter()
            calculate(h)
            runs.append(ms(t))
        print(f"{name:40s} {statistics.median(runs):7.0f}ms {max(runs):7.0f}ms")

    h = SHAPES["CA parent + 2 kids, $32k, rent"]
    year, month = periods(date.today())
    print(f"\n{'program (fresh simulation, CA parent + 2 kids)':48s} {'median':>8s}")
    for prog in (x for x in PROGRAMS if "CA" in x.states):
        runs = []
        for _ in range(reps):
            sim = Simulation(situation=build_situation(h, year)[0])
            t = time.perf_counter()
            sim.calculate(prog.variable, period_for(prog.variable, year, month))
            runs.append(ms(t))
        print(f"{prog.id:48s} {statistics.median(runs):7.0f}ms")


if __name__ == "__main__":
    main()
