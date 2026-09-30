"""Run PolicyEngine-US for one household and report each in-scope program."""

from datetime import date

from policyengine_us import Simulation

from .household import Household
from .programs import PROGRAMS, Program

# What PolicyEngine silently uses when we don't know a value. Reported back to the
# caller as assumptions for every unknown field.
ENGINE_DEFAULTS = {
    "employment_income": 0,
    "self_employment_income": 0,
    "weekly_hours_worked": 0,
    "is_pregnant": False,
    "is_disabled": False,
    "immigration_status": "CITIZEN",
}
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


def build_situation(h: Household, year: str) -> tuple[dict, list[str]]:
    """PolicyEngine situation for one household (one tax unit, SPM unit and family),
    plus the list of assumptions made for unknown fields."""
    assumptions: list[str] = []
    people: dict[str, dict] = {}
    for p in h.people:
        person = {"age": {year: p.age}}
        for field, variable in PERSON_INPUTS.items():
            value = getattr(p, field)
            if value is None:
                assumptions.append(f"{p.id}.{field}={ENGINE_DEFAULTS[field]}")
            else:
                person[variable] = {year: value}
        people[p.id] = person

    head = next(p.id for p in h.people if p.relationship == "head")
    if h.rent is None:
        assumptions.append("rent=0")
    else:
        people[head]["pre_subsidy_rent"] = {year: h.rent}

    ids = list(people)
    couple = [p.id for p in h.people if p.relationship in ("head", "spouse")]
    marital_units = {"couple": {"members": couple}}
    marital_units |= {f"mu_{p.id}": {"members": [p.id]} for p in h.people if p.id not in couple}

    spm_unit: dict = {"members": ids}
    if h.childcare_expenses is None:
        assumptions.append("childcare_expenses=0")
    else:
        spm_unit["spm_unit_pre_subsidy_childcare_expenses"] = {year: h.childcare_expenses}

    household: dict = {"members": ids, "state_code": {year: h.state}}
    if h.county:
        household["county"] = {year: h.county}
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
    situation, assumptions = build_situation(h, year)
    sim = Simulation(situation=situation)
    person_ids = [p.id for p in h.people]
    programs = [_program_result(sim, p, year, month, person_ids) for p in PROGRAMS if h.state in p.states]
    return {"as_of": as_of.isoformat(), "state": h.state, "programs": programs, "assumptions": assumptions}
