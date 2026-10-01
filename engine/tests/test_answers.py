"""Each answer reaches the engine input that the programs actually read (regressions from
the Stage 2 review: answers that were silently ignored or placed on the wrong person).

Expectations are the direction of a rule, with the rule cited, not engine numbers."""

from datetime import date

from policyengine_us import Simulation

from unclaimed_engine.calculate import build_situation, calculate
from unclaimed_engine.household import Household

AS_OF = date(2026, 9, 15)
LA, COOK = "LOS_ANGELES_COUNTY_CA", "COOK_COUNTY_IL"


def programs(state, county, people, **kw):
    h = Household(state=state, county=county, as_of=AS_OF, people=people, **kw)
    return {p["id"]: p for p in calculate(h)["programs"]}


def test_undocumented_parent_gets_no_federal_credits_but_gets_caleitc():
    # Federal EITC and CTC require an SSN valid for work (IRC 32(m), 24(h)(7)); CalEITC
    # accepts an ITIN (Cal. Rev. & Tax. Code 17052).
    def credits(status):
        r = programs("CA", LA, [{"id": "a", "relationship": "head", "age": 30, "employment_income": 20_000,
                                 "immigration_status": status},
                                {"id": "c", "relationship": "child", "age": 5, "immigration_status": "CITIZEN"}])
        return r["eitc"]["amount"], r["ctc"]["amount"], r["ca_eitc"]["amount"]
    eitc, ctc, caleitc = credits("UNDOCUMENTED")
    assert eitc == 0 and ctc == 0 and caleitc > 0
    assert credits("CITIZEN")[0] > 0


def test_medical_costs_count_for_the_elderly_member():
    # SNAP deducts medical costs of elderly or disabled members only (7 CFR 273.9(d)(3)).
    def snap(spouse_medical):
        return programs("IL", COOK, [{"id": "a", "relationship": "head", "age": 40, "employment_income": 18_000,
                                      "weekly_hours_worked": 30},
                                     {"id": "b", "relationship": "spouse", "age": 67, "medical_expenses": spouse_medical}],
                        rent=9_000)["snap"]["amount"]
    assert snap(3_600) > snap(0)


def test_care_needs_own_utility_bill_not_heat_outside_rent():
    # A renter whose heat is in the rent but who pays their own electric bill still gets CARE.
    r = programs("CA", LA, [{"id": "a", "relationship": "head", "age": 30, "employment_income": 15_000}],
                 rent=12_000, heat_included_in_rent=True, electricity_bill=1_200)
    assert r["ca_care"]["eligible"] and r["ca_care"]["amount"] > 0


def test_years_in_us_reaches_medicaid():
    # Most lawful permanent residents wait 5 years for federally funded Medicaid (8 U.S.C. 1613).
    def eligible(years):
        r = programs("IL", COOK, [{"id": "a", "relationship": "head", "age": 35, "employment_income": 12_000,
                                   "immigration_status": "LEGAL_PERMANENT_RESIDENT", "years_in_us": years}])
        return r["medicaid"]["eligible"]
    assert eligible(10) and not eligible(2)


def test_tax_unit_ids_are_known_to_medicaid():
    # The engine reads tax unit ID 0 as "no claiming unit", so IDs start at 1.
    h = Household(state="IL", county=COOK, as_of=AS_OF, people=[
        {"id": "a", "relationship": "head", "age": 50, "employment_income": 20_000},
        {"id": "b", "relationship": "child", "age": 10},
        {"id": "c", "relationship": "child", "age": 22, "employment_income": 15_000}])
    sim = Simulation(situation=build_situation(h, "2026")[0])
    assert sim.calculate("medicaid_has_known_claiming_tax_unit", "2026").all()


def test_savings_is_a_household_total():
    # CalWORKs has a resource limit; a large household balance must reach it.
    def calworks(savings):
        return programs("CA", LA, [{"id": "a", "relationship": "head", "age": 30, "employment_income": 0},
                                   {"id": "c", "relationship": "child", "age": 3}],
                        rent=12_000, savings=savings)["ca_calworks"]["eligible"]
    assert calworks(0) and not calworks(50_000)
