"""Run PolicyEngine-US for one household and report each in-scope program."""

from dataclasses import dataclass
from datetime import date

from policyengine_us import Simulation
from policyengine_us.system import system

from .dictionary import load
from .geo import counties_for_zip, county_fips, resolve_county, state_fips
from .household import Household
from .programs import PROGRAMS, Program

DICTIONARY = load()
# Entity key -> the situation's group name (e.g. tax_unit -> tax_units), from the engine.
GROUPS = {e.key: e.plural for e in system.entities}
# Federal tax credits need an SSN valid for work (IRC 32(m), 24(h)(7)); PolicyEngine reads
# that from ssn_card_type, not immigration_status. Our decision, defined once: citizens
# have a citizen's SSN, undocumented people have none, and every other status in the
# engine's list (permanent residents, refugees, asylees, DACA, TPS, parolees, ...) is
# authorized to work and so can hold an SSN valid for work.
SSN_CARD_FOR_STATUS = {"CITIZEN": "CITIZEN", "UNDOCUMENTED": "NONE"}
SSN_CARD_OTHERWISE = "NON_CITIZEN_VALID_EAD"


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


def _put(target: dict, variable: str, year: str, value, money: bool = False) -> None:
    """Set an input for the whole year. Monthly variables get a value for each month;
    money (yearly in our units) is split evenly across them."""
    period = system.variables[variable].definition_period
    if period == "eternity":
        target[variable] = {"ETERNITY": value}
    elif period == "month":
        per_month = value / 12 if money else value
        target[variable] = {f"{year}-{m:02d}": per_month for m in range(1, 13)}
    else:
        target[variable] = {year: value}


@dataclass(frozen=True)
class _Structure:
    """Who is who, from the stated relationships (never PolicyEngine's age-based guess,
    which makes an 18-year-old "child" the spouse)."""
    h: Household
    county: str | None
    head: str
    spouse: tuple[str, ...]
    dependents: tuple[str, ...]
    own_filers: tuple[str, ...]  # adult children, filing their own return

    @classmethod
    def of(cls, h: Household, county: str | None, year: str) -> "_Structure":
        # Qualifying child: under 19, under 24 if a full-time student (IRC 152(c)(3)(A)), or
        # disabled at any age. The ages are the engine's own parameters for the year.
        ages = system.parameters.gov.irs.dependent.ineligible_age(f"{year}-01-01")
        kids = [p for p in h.people if p.relationship == "child"]
        dependents = tuple(p.id for p in kids if p.age < ages.non_student or p.is_disabled
                           or (p.age < ages.student and p.is_full_time_college_student))
        return cls(h, county,
                   head=next(p.id for p in h.people if p.relationship == "head"),
                   spouse=tuple(p.id for p in h.people if p.relationship == "spouse"),
                   dependents=dependents,
                   own_filers=tuple(p.id for p in kids if p.id not in dependents))

    @property
    def ids(self) -> list[str]:
        return [p.id for p in self.h.people]

    @property
    def tax_units(self) -> dict[str, list[str]]:
        """Tax unit name -> members: the head's return first, then each own filer's."""
        return {"tax_unit": [self.head, *self.spouse, *self.dependents]} | {f"tax_unit_{i}": [i] for i in self.own_filers}

    def tax_unit_of(self, pid: str) -> int:
        """The person's tax unit ID. IDs start at 1: the engine reads 0 as "no claiming unit"."""
        return next(n for n, members in enumerate(self.tax_units.values(), start=1) if pid in members)


# How our code sets each `derived` input in the dictionary. Person inputs return
# {person id: value}; group inputs return one value for the household's main unit, or
# {unit name: value} for each unit (None = leave unset). The dictionary tests check these
# keys match `derived` exactly.
DERIVERS = {
    "age": lambda s: {p.id: p.age for p in s.h.people},
    "state_code": lambda s: s.h.state,
    "county": lambda s: s.county,
    "zip_code": lambda s: s.h.zip,
    "is_tax_unit_head": lambda s: {i: i == s.head or i in s.own_filers for i in s.ids},
    "is_tax_unit_spouse": lambda s: {i: i in s.spouse for i in s.ids},
    "is_tax_unit_dependent": lambda s: {i: i in s.dependents for i in s.ids},
    "county_fips": lambda s: county_fips(s.county) if s.county else None,
    "state_fips": lambda s: state_fips(s.h.state),
    "tax_unit_id": lambda s: {name: n for n, name in enumerate(s.tax_units, start=1)},
    "medicaid_claiming_tax_unit_id": lambda s: {i: s.tax_unit_of(i) for i in s.ids},
    "is_household_head": lambda s: {i: i == s.head for i in s.ids},
    "is_related_to_head_or_spouse": lambda s: {i: True for i in s.ids},
    "own_children_in_household": lambda s: {
        i: sum(p.relationship == "child" for p in s.h.people) if i in (s.head, *s.spouse) else 0 for i in s.ids},
    "cohabitating_spouses": lambda s: bool(s.spouse),
    "tenant_pays_utilities": lambda s: (
        None if s.h.electricity_bill is None and s.h.gas_bill is None
        else bool(s.h.electricity_bill) or bool(s.h.gas_bill)),
    "ssn_card_type": lambda s: {
        p.id: SSN_CARD_FOR_STATUS.get(p.immigration_status, SSN_CARD_OTHERWISE)
        for p in s.h.people if p.immigration_status is not None},
    "living_arrangements_allow_for_food_preparation": lambda s: True,
}


def build_situation(h: Household, year: str, county: str | None = None) -> tuple[dict, list[dict]]:
    """PolicyEngine situation for one household, plus what was assumed for each unanswered
    question: {question, person, value (the engine's default), status: unknown|declined}.
    `county` overrides h.county (used when it was resolved from the ZIP)."""
    s = _Structure.of(h, county or h.county, year)
    declined = set(h.declined)
    assumptions: list[dict] = []
    people: dict[str, dict] = {pid: {} for pid in s.ids}
    couple = [s.head, *s.spouse]
    situation = {
        "people": people,
        "tax_units": {name: {"members": members} for name, members in s.tax_units.items()},
        "spm_units": {"spm_unit": {"members": s.ids}},
        "families": {"family": {"members": s.ids}},
        "marital_units": {"couple": {"members": couple}}
        | {f"mu_{pid}": {"members": [pid]} for pid in s.ids if pid not in couple},
        "households": {"household": {"members": s.ids}},
    }
    main = {"tax_unit": situation["tax_units"]["tax_unit"], "spm_unit": situation["spm_units"]["spm_unit"],
            "family": situation["families"]["family"], "marital_unit": situation["marital_units"]["couple"],
            "household": situation["households"]["household"]}

    for q in DICTIONARY.questions:
        answers = [(p.id, getattr(p, q.id)) for p in h.people] if q.entity == "person" else [(None, getattr(h, q.id))]
        for pid, value in answers:
            if value is None:
                key = f"{pid}.{q.id}" if pid else q.id
                assumptions.append({"question": q.id, "person": pid, "value": engine_default(q.engine[0]),
                                    "status": "declined" if key in declined else "unknown"})
                continue
            for var in q.engine:
                entity = system.variables[var].entity.key
                if entity != "person":
                    target = main[entity]
                else:  # a household answer on a per-person input goes where the dictionary says
                    target = people[pid] if pid else people[{"head": s.head}[q.on_person]]
                _put(target, var, year, value, money=q.answer["type"] == "money")

    for var, derive in DERIVERS.items():
        value = derive(s)
        if value is None:
            continue
        entity = system.variables[var].entity.key
        if entity == "person":
            for pid, v in value.items():
                _put(people[pid], var, year, v)
        elif isinstance(value, dict):  # one value per unit of this entity
            for name, v in value.items():
                _put(situation[GROUPS[entity]][name], var, year, v)
        else:
            _put(main[entity], var, year, value)
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
        assumptions.append({"question": "county", "person": None, "value": used, "status": "unknown"})
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
        # Said out loud on the results screen: what we assumed about everything we didn't ask.
        "statements": [g.statement for g in DICTIONARY.assumed if g.statement],
    }
