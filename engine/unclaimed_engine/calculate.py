"""Run PolicyEngine-US for one household and report each in-scope program."""

from datetime import date

from policyengine_us import Simulation
from policyengine_us.system import system

from .geo import resolve_county
from .household import Household
from .programs import PROGRAMS, Program

# Our field -> PolicyEngine input variable. The *_before_lsr variables are the true
# inputs; employment_income etc. are derived from them (plus behavioural responses).
PERSON_INPUTS = {
    "employment_income": "employment_income_before_lsr",
    "self_employment_income": "self_employment_income_before_lsr",
    "weekly_hours_worked": "weekly_hours_worked_before_lsr",
    "is_pregnant": "is_pregnant",
    "is_disabled": "is_disabled",
    "immigration_status": "immigration_status",
}


def engine_default(variable: str):
    """What PolicyEngine silently uses when a value isn't given, read from PolicyEngine
    itself so our assumption reports can't drift from the engine."""
    default = system.variables[variable].default_value
    default = getattr(default, "name", default)  # enums -> their name, e.g. CITIZEN
    return int(default) if isinstance(default, float) and default.is_integer() else default


def build_situation(h: Household, year: str, county: str | None = None) -> tuple[dict, list[str]]:
    """PolicyEngine situation for one household (one tax unit, SPM unit and family),
    plus the list of assumptions made for unknown fields. `county` overrides h.county
    (used when it was resolved from the ZIP)."""
    county = county or h.county
    assumptions: list[str] = []
    people: dict[str, dict] = {}
    for p in h.people:
        person = {"age": {year: p.age}}
        for field, variable in PERSON_INPUTS.items():
            value = getattr(p, field)
            if value is None:
                assumptions.append(f"{p.id}.{field}={engine_default(variable)}")
            else:
                person[variable] = {year: value}
        people[p.id] = person

    head = next(p.id for p in h.people if p.relationship == "head")
    if h.rent is None:
        assumptions.append(f"rent={engine_default('pre_subsidy_rent')}")
    else:
        people[head]["pre_subsidy_rent"] = {year: h.rent}

    ids = list(people)
    couple = [p.id for p in h.people if p.relationship in ("head", "spouse")]
    marital_units = {"couple": {"members": couple}}
    marital_units |= {f"mu_{p.id}": {"members": [p.id]} for p in h.people if p.id not in couple}

    spm_unit: dict = {"members": ids}
    if h.childcare_expenses is None:
        assumptions.append(f"childcare_expenses={engine_default('spm_unit_pre_subsidy_childcare_expenses')}")
    else:
        spm_unit["spm_unit_pre_subsidy_childcare_expenses"] = {year: h.childcare_expenses}

    household: dict = {"members": ids, "state_code": {year: h.state}}
    if county:
        household["county"] = {year: county}
    else:
        # PolicyEngine would otherwise use the first county in the state (Alameda / Adams).
        assumptions.append("county=unknown (engine uses the first county in the state)")

    situation = {
        "people": people,
        "tax_units": {"tax_unit": {"members": ids}},
        "spm_units": {"spm_unit": spm_unit},
        "families": {"family": {"members": ids}},
        "marital_units": marital_units,
        "households": {"household": household},
    }
    return situation, assumptions


def _program_result(sim: Simulation, program: Program, year: str, month: str, person_ids: list[str]) -> dict:
    period = month if sim.tax_benefit_system.variables[program.variable].definition_period == "month" else year
    total = float(sim.calculate(program.variable, period).sum())
    monthly = total if period == month else total / 12
    result = {
        "id": program.id,
        "name": program.name,
        "per": program.per,
        "amount": round(monthly if program.per == "month" else monthly * 12, 2),
        "monthly_value": round(monthly, 2),
    }
    if program.eligibility:
        flags = sim.calculate(program.eligibility, year)
        result["eligible_people"] = [pid for pid, ok in zip(person_ids, flags) if ok]
        result["eligible"] = bool(result["eligible_people"])
        result.pop("amount")  # value of coverage, not money paid to the person
    else:
        result["eligible"] = total > 0
    return result


def calculate(h: Household) -> dict:
    as_of = h.as_of or date.today()
    year, month = str(as_of.year), f"{as_of:%Y-%m}"
    county, candidates = h.county, [h.county] if h.county else []
    if not county and h.zip:
        county, candidates = resolve_county(h.zip, h.state)
    situation, assumptions = build_situation(h, year, county)
    sim = Simulation(situation=situation)
    person_ids = [p.id for p in h.people]
    programs = [_program_result(sim, p, year, month, person_ids) for p in PROGRAMS if h.state in p.states]
    return {
        "as_of": as_of.isoformat(),
        "state": h.state,
        "county": county,
        # More than one entry: the ZIP is split between counties; ask which one.
        "county_candidates": candidates,
        "programs": programs,
        "assumptions": assumptions,
    }
