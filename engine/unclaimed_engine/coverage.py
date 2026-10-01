"""Coverage: which PolicyEngine inputs do our programs actually read? Traces every
in-scope program over a grid of CA + IL households. Used by the coverage test (every
input read must be classified in the dictionary) and by the scripts that explore inputs.
"""

import itertools
from collections import defaultdict
from datetime import date

from policyengine_us import Simulation
from policyengine_us.system import system

from .calculate import build_situation, period_for, periods
from .dictionary import load
from .household import Household
from .programs import PROGRAMS, SUPPORTED_STATES


def _person(i, rel, age, inc, **kw):
    return {"id": i, "relationship": rel, "age": age, "employment_income": inc, **kw}


# Household shapes chosen to reach every program branch: children of each age band
# (including an infant), couples, seniors (one on SSI), disability (adult and child),
# pregnancy, adult children (filing alone, or a student), non-citizens, a homeowner.
SHAPES = {
    "single": lambda inc: [_person("a", "head", 30, inc, weekly_hours_worked=30)],
    "parent_2kids": lambda inc: [_person("a", "head", 34, inc), _person("b", "child", 4, 0), _person("c", "child", 9, 0)],
    "couple_baby_teen": lambda inc: [_person("a", "head", 38, inc), _person("b", "spouse", 36, 0),
                                     _person("c", "child", 1, 0), _person("d", "child", 15, 0)],
    "senior": lambda inc: [_person("a", "head", 70, inc)],
    "disabled": lambda inc: [_person("a", "head", 45, inc, is_disabled=True)],
    "pregnant": lambda inc: [_person("a", "head", 24, inc, is_pregnant=True)],
    "adult_child": lambda inc: [_person("a", "head", 50, inc), _person("b", "child", 21, 15_000)],
    "student_child": lambda inc: [_person("a", "head", 50, inc),
                                  _person("b", "child", 20, 6_000, is_full_time_college_student=True)],
    "infant": lambda inc: [_person("a", "head", 26, inc), _person("b", "child", 0, 0)],
    "senior_couple_ssi": lambda inc: [_person("a", "head", 72, inc, receives_ssi=True), _person("b", "spouse", 68, 0)],
    "disabled_child": lambda inc: [_person("a", "head", 40, inc), _person("b", "child", 10, 0, is_disabled=True)],
    "lpr_family": lambda inc: [_person("a", "head", 35, inc, immigration_status="LEGAL_PERMANENT_RESIDENT", years_in_us=2),
                               _person("b", "child", 6, 0)],
    "undocumented_family": lambda inc: [_person("a", "head", 35, inc, immigration_status="UNDOCUMENTED"),
                                        _person("b", "child", 6, 0, immigration_status="CITIZEN")],
}
# Shapes that are homeowners rather than renters.
OWNERS = {"senior_couple_ssi"}
INCOMES = (0, 15_000, 35_000, 70_000)


def _answered(people: list[dict]) -> tuple[list[dict], dict]:
    """The same people with every dictionary question answered at its high what-if value
    (person questions for the head, household questions once), so answers that open new
    engine branches (e.g. heating with gas reads the gas bill) are traced too."""
    d = load()
    head = {**people[0], **{q.id: q.what_if[1] for q in d.questions if q.entity == "person"}}
    return [head, *people[1:]], {q.id: q.what_if[1] for q in d.questions if q.entity == "household"}


def grid(incomes=INCOMES):
    """(label, Household) for every state x shape x income, unanswered and fully answered."""
    for state, (shape, make), inc in itertools.product(SUPPORTED_STATES, SHAPES.items(), incomes):
        housing = ({"housing_tenure": "OWNER_WITH_MORTGAGE", "mortgage_payments": 9_000} if shape in OWNERS
                   else {"rent": 12_000})
        yield f"{state}/{shape}/{inc}", Household(state=state, people=make(inc), childcare_expenses=0, **housing)
        people, answers = _answered(make(inc))
        yield f"{state}/{shape}/{inc}/answered", Household(state=state, people=people, **answers)


def is_input(name: str) -> bool:
    v = system.variables[name]
    return not v.formulas and not getattr(v, "adds", None) and not getattr(v, "subtracts", None)


def _walk(node, seen: set) -> None:
    seen.add(node.name)
    for child in node.children:
        _walk(child, seen)


def traced_inputs(households) -> dict[str, dict]:
    """input variable -> {"programs": set of program ids, "households": count}."""
    year, month = periods(date.today())
    found: dict[str, dict] = defaultdict(lambda: {"programs": set(), "households": 0})
    for _, h in households:
        situation, _ = build_situation(h, year)
        read = set()
        for prog in (p for p in PROGRAMS if h.state in p.states):
            sim = Simulation(situation=situation)
            sim.trace = True
            for var in (prog.variable, prog.eligibility, *prog.explain):
                if var:
                    sim.calculate(var, period_for(var, year, month))
            seen: set[str] = set()
            for root in sim.tracer.trees:
                _walk(root, seen)
            for name in seen:
                if is_input(name):
                    found[name]["programs"].add(prog.id)
                    read.add(name)
        for name in read:
            found[name]["households"] += 1
    return dict(found)
