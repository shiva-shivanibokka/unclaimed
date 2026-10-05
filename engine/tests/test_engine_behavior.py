"""Guards for PolicyEngine behavior our design depends on (see
engine/research/). These are behavior checks, not correctness checks: if a PolicyEngine upgrade
changes one, this fails loudly so we revisit the design. Built on our engine's real
inputs, never the research scripts' helpers."""

from datetime import date

from policyengine_us import Simulation
from policyengine_us.system import system

from unclaimed_engine import batch
from unclaimed_engine.calculate import build_situation, calculate
from unclaimed_engine.household import Household

AS_OF = date(2026, 9, 15)


def sim_for(h: Household) -> Simulation:
    return Simulation(situation=build_situation(h, str(AS_OF.year))[0])


def test_missing_county_falls_back_to_a_county_in_the_state():
    # Unknown county silently becomes the state's first county; we report it as an assumption.
    for state in ("CA", "IL"):
        h = Household(state=state, as_of=AS_OF, people=[{"id": "a", "relationship": "head", "age": 30}])
        county = sim_for(h).calculate("county", "2026").decode()[0].name
        assert county.endswith(f"_{state}")
        assert {"question": "county", "person": None, "value": county, "status": "unknown"} in calculate(h)["assumptions"]


def test_unset_inputs_default_to_citizen_and_zero():
    assert system.variables["immigration_status"].default_value.name == "CITIZEN"
    assert system.variables["employment_income_before_lsr"].default_value == 0


def test_period_units():
    # Income inputs are yearly; SNAP and WIC are monthly; tax credits and Medicaid yearly.
    v = system.variables
    assert v["employment_income_before_lsr"].definition_period == "year"
    assert v["pre_subsidy_rent"].definition_period == "year"
    assert {v["snap"].definition_period, v["wic"].definition_period} == {"month"}
    assert {v["eitc"].definition_period, v["ctc"].definition_period, v["medicaid"].definition_period} == {"year"}


def test_county_changes_the_aca_credit():
    # Single 55-year-old at $45K: the credit differs by county, so ZIP -> county is load-bearing.
    def ptc(county):
        h = Household(state="CA", county=county, as_of=AS_OF,
                      people=[{"id": "a", "relationship": "head", "age": 55, "employment_income": 45_000}])
        return next(p["amount"] for p in calculate(h)["programs"] if p["id"] == "aca_ptc")
    values = {ptc(c) for c in ("LOS_ANGELES_COUNTY_CA", "ALAMEDA_COUNTY_CA", "MODOC_COUNTY_CA")}
    assert len(values) == 3


def test_batched_variants_return_one_result_per_variant_in_order():
    h = Household(state="IL", county="COOK_COUNTY_IL", as_of=AS_OF,
                  people=[{"id": "a", "relationship": "head", "age": 35, "weekly_hours_worked": 40},
                          {"id": "c", "relationship": "child", "age": 4}])
    incomes = [0, 20_000, 200_000, 20_000]
    results = batch.evaluate(h, [{("a", "employment_income"): x} for x in incomes])
    assert len(results) == 4 and results[1] == results[3] and results[0] != results[2]
    alone = batch.evaluate(h, [{("a", "employment_income"): 200_000}])[0]
    assert alone == results[2]  # a copy in a batch computes exactly as on its own
