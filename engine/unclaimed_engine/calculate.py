"""Run PolicyEngine-US for one household and report each in-scope program."""

from datetime import date

from policyengine_us import Simulation
from policyengine_us.system import system

from .geo import counties_for_zip, resolve_county
from .household import Household
from .programs import PROGRAMS, Program

# Our field -> the PolicyEngine input variables it sets. The *_before_lsr variables are
# the true inputs (employment_income etc. are derived from them). One answer can feed
# several inputs: "has a disability that limits work" is also SSI's disability test,
# which PolicyEngine keeps as a separate input that otherwise defaults to False.
PERSON_INPUTS = {
    "employment_income": ("employment_income_before_lsr",),
    "self_employment_income": ("self_employment_income_before_lsr",),
    "weekly_hours_worked": ("weekly_hours_worked_before_lsr",),
    "is_pregnant": ("is_pregnant",),
    "is_disabled": ("is_disabled", "meets_ssi_disability_criteria"),
    "immigration_status": ("immigration_status",),
}
# A child can be claimed as a qualifying child when under this age (IRC 152(c)(3)(A)),
# or at any age when permanently disabled. Full-time students 19-23 also qualify, but we
# don't ask about school yet, so older children file their own return (stated as an
# assumption; it can only understate the parents' credits, never overstate them).
QUALIFYING_CHILD_AGE = 19


def periods(as_of: date) -> tuple[str, str]:
    """(year, month) periods for a screening date."""
    return str(as_of.year), f"{as_of:%Y-%m}"


def period_for(variable: str, year: str, month: str) -> str:
    """The period to calculate a variable for, from the variable's own definition."""
    return month if system.variables[variable].definition_period == "month" else year


def engine_default(variable: str):
    """What PolicyEngine silently uses when a value isn't given, read from PolicyEngine
    itself so our assumption reports can't drift from the engine."""
    default = system.variables[variable].default_value
    default = getattr(default, "name", default)  # enums -> their name, e.g. CITIZEN
    return int(default) if isinstance(default, float) and default.is_integer() else default


def build_situation(h: Household, year: str, county: str | None = None) -> tuple[dict, list[str]]:
    """PolicyEngine situation for one household, plus the assumptions made for unknown
    fields. `county` overrides h.county (used when it was resolved from the ZIP)."""
    county = county or h.county
    assumptions: list[str] = []
    people: dict[str, dict] = {}
    for p in h.people:
        person = {"age": {year: p.age}}
        for field, variables in PERSON_INPUTS.items():
            value = getattr(p, field)
            if value is None:
                assumptions.append(f"{p.id}.{field}={engine_default(variables[0])}")
            else:
                person |= {v: {year: value} for v in variables}
        people[p.id] = person

    # Tax roles come from the stated relationships, never from PolicyEngine's age-based
    # guess (which makes an 18-year-old "child" the spouse).
    head = next(p for p in h.people if p.relationship == "head")
    spouse = [p.id for p in h.people if p.relationship == "spouse"]
    dependents, own_filers = [], []
    for p in h.people:
        if p.relationship != "child":
            continue
        if p.age < QUALIFYING_CHILD_AGE or p.is_disabled:
            dependents.append(p.id)
        else:
            own_filers.append(p.id)
            assumptions.append(f"{p.id}.files_own_tax_return=True (age {QUALIFYING_CHILD_AGE}+, not a full-time student)")
    for pid in people:
        people[pid] |= {
            "is_tax_unit_head": {year: pid == head.id or pid in own_filers},
            "is_tax_unit_spouse": {year: pid in spouse},
            "is_tax_unit_dependent": {year: pid in dependents},
        }
    tax_units = {"tax_unit": {"members": [head.id, *spouse, *dependents]}}
    tax_units |= {f"tax_unit_{pid}": {"members": [pid]} for pid in own_filers}

    if h.rent is None:
        assumptions.append(f"rent={engine_default('pre_subsidy_rent')}")
    else:
        people[head.id]["pre_subsidy_rent"] = {year: h.rent}

    ids = list(people)
    couple = [head.id, *spouse]
    marital_units = {"couple": {"members": couple}}
    marital_units |= {f"mu_{pid}": {"members": [pid]} for pid in ids if pid not in couple}

    spm_unit: dict = {"members": ids}
    if h.childcare_expenses is None:
        assumptions.append(f"childcare_expenses={engine_default('spm_unit_pre_subsidy_childcare_expenses')}")
    else:
        spm_unit["spm_unit_pre_subsidy_childcare_expenses"] = {year: h.childcare_expenses}

    household: dict = {"members": ids, "state_code": {year: h.state}}
    if county:
        household["county"] = {year: county}

    situation = {
        "people": people,
        "tax_units": tax_units,
        "spm_units": {"spm_unit": spm_unit},
        "families": {"family": {"members": ids}},
        "marital_units": marital_units,
        "households": {"household": household},
    }
    return situation, assumptions


def _plain(value):
    """numpy / enum values -> JSON: bools, rounded numbers, enum names."""
    if hasattr(value, "name"):
        return value.name
    if isinstance(value, (bool, int, float)) or hasattr(value, "item"):
        value = value.item() if hasattr(value, "item") else value
        return round(value, 4) if isinstance(value, float) else value
    return str(value)


def _explain(sim: Simulation, variable: str, year: str, month: str, person_ids: list[str]) -> dict:
    """One fact behind a result. Label, unit, entity and period all come from PolicyEngine.
    Group-level facts are the main unit's (the head's tax unit; the one SPM unit)."""
    meta = system.variables[variable]
    values = sim.calculate(variable, period_for(variable, year, month))
    if hasattr(values, "decode"):  # EnumArray -> Enum members, not indices
        values = values.decode()
    fact = {"variable": variable, "label": meta.label, "unit": meta.unit, "period": meta.definition_period}
    if meta.entity.key == "person":
        fact["by_person"] = {pid: _plain(v) for pid, v in zip(person_ids, values)}
    else:
        fact["value"] = _plain(values[0])
    return fact


def _program_result(sim: Simulation, program: Program, state: str, year: str, month: str, person_ids: list[str]) -> dict:
    period = period_for(program.variable, year, month)
    total = float(sim.calculate(program.variable, period).sum())
    monthly = total if period == month else total / 12
    result = {
        "id": program.id,
        "name": program.name_in(state),
        "per": program.per,
        "amount": round(monthly if program.per == "month" else monthly * 12, 2),
        "monthly_value": round(monthly, 2),
    }
    if program.eligibility:
        flags = sim.calculate(program.eligibility, period_for(program.eligibility, year, month))
        if system.variables[program.eligibility].entity.key == "person":
            result["eligible_people"] = [pid for pid, ok in zip(person_ids, flags) if ok]
        result["eligible"] = bool(flags.any())
    else:
        result["eligible"] = total > 0
    if program.coverage:
        result.pop("amount")  # value of coverage, not money paid to the person
    result["explain"] = [_explain(sim, v, year, month, person_ids) for v in program.explain]
    return result


def calculate(h: Household) -> dict:
    as_of = h.as_of or date.today()
    year, month = periods(as_of)
    county, candidates = h.county, [h.county] if h.county else []
    if h.zip and not county:
        county, candidates = resolve_county(h.zip, h.state)
    elif h.zip and county not in [c for c, _ in counties_for_zip(h.zip, h.state)]:
        raise ValueError(f"{county} does not contain ZIP {h.zip}")
    situation, assumptions = build_situation(h, year, county)
    sim = Simulation(situation=situation)
    if not county:
        # Report the county PolicyEngine actually falls back to, read from the engine.
        used = sim.calculate("county", year).decode()[0].name
        assumptions.append(f"county={used} (unknown; engine default)")
    person_ids = [p.id for p in h.people]
    programs = [_program_result(sim, p, h.state, year, month, person_ids) for p in PROGRAMS if h.state in p.states]
    return {
        "as_of": as_of.isoformat(),
        "state": h.state,
        "county": county,
        # More than one entry: the ZIP is split between counties; ask which one.
        "county_candidates": candidates,
        "programs": programs,
        "assumptions": assumptions,
    }
