"""Engine results vs. official published figures (never vs. the engine's own output).

Sources:
- SNAP FY2026 (Oct 1 2025 - Sep 30 2026) max allotments, 48 states: USDA FNS,
  https://www.fns.usda.gov/snap/allotment/cola  (1 person $298, 4 people $994)
- EITC / CTC tax year 2026: IRS Rev. Proc. 2025-32 (EITC max $664 / $4,427 / $8,231 for
  0 / 1 / 3+ children; plateau earned income $8,680 / $13,020 / $18,290; phaseout starts
  $10,860 / $23,890 for non-joint filers). CTC $2,200 per child, refundable up to $1,700,
  refundable part = 15% of earned income above $2,500 (IRC 24(d)).
- Illinois EITC = 20% of the federal EITC for tax years 2023+ (35 ILCS 5/212(a)).
- Medicaid expansion adults: income up to 138% FPL (CA and IL both expanded).
- WIC: pregnant women with income up to 185% FPL are categorically in scope.
"""

import math
from datetime import date

import pytest
from policyengine_us import Simulation

from unclaimed_engine.calculate import build_situation, calculate
from unclaimed_engine.household import Household

FY2026 = date(2026, 9, 15)  # inside SNAP FY2026 and tax year 2026


def screen(state, people, county, **kw):
    h = Household(
        state=state, county=county, as_of=FY2026,
        people=[{"immigration_status": "CITIZEN", "is_pregnant": False, "is_disabled": False,
                 "self_employment_income": 0, **p} for p in people],
        rent=kw.pop("rent", 0), childcare_expenses=kw.pop("childcare_expenses", 0), **kw,
    )
    return {p["id"]: p for p in calculate(h)["programs"]}


SF, COOK = "SAN_FRANCISCO_COUNTY_CA", "COOK_COUNTY_IL"
adult = lambda i, age=30, inc=0, rel="head", **kw: {"id": i, "relationship": rel, "age": age, "employment_income": inc, **kw}
kid = lambda i, age: {"id": i, "relationship": "child", "age": age, "employment_income": 0}


def snap_parts(state, people, county):
    h = Household(state=state, county=county, as_of=FY2026, rent=0, childcare_expenses=0,
                  people=[{"immigration_status": "CITIZEN", "is_pregnant": False, "is_disabled": False,
                           "self_employment_income": 0, **p} for p in people])
    sim = Simulation(situation=build_situation(h, "2026")[0])
    return {k: float(sim.calculate(k, "2026-09").sum()) for k in ("snap", "snap_max_allotment", "snap_net_income")}


@pytest.mark.parametrize("state,county,people,official_max", [
    # Pregnant, so exempt from the ABAWD work rule.
    ("CA", "SAN_FRANCISCO_COUNTY_CA", [{"id": "a", "relationship": "head", "age": 30, "employment_income": 0, "is_pregnant": True}], 298),
    ("IL", "COOK_COUNTY_IL", [{"id": "a", "relationship": "head", "age": 30, "employment_income": 0},
                              {"id": "b", "relationship": "spouse", "age": 30, "employment_income": 0},
                              {"id": "c", "relationship": "child", "age": 4, "employment_income": 0},
                              {"id": "d", "relationship": "child", "age": 8, "employment_income": 0}], 994),
])
def test_snap_benefit_formula(state, county, people, official_max):
    # Zero earnings, but cash aid (CalWORKs / TANF) counts as income, so the benefit is
    # max allotment - 30% of net income, rounded up to the next dollar (7 CFR 273.10(e)(2)(ii)(A)).
    s = snap_parts(state, people, county)
    assert s["snap_max_allotment"] == official_max
    assert s["snap"] == official_max - math.ceil(0.3 * s["snap_net_income"])


def test_snap_abawd_20_hour_work_rule():
    # P.L. 119-21 (H.R.1) sec. 10102: adults 18-64 without dependents must work 20 h/week
    # (7 U.S.C. 2015(o)). Engine limitation: it ignores the 3-countable-months allowance
    # (7 CFR 273.24(b)), so a new applicant who doesn't work shows $0. See engine/README.md.
    works = screen("CA", [adult("a", inc=6_000, weekly_hours_worked=20)], SF)["snap"]
    idle = screen("CA", [adult("a", inc=6_000, weekly_hours_worked=0)], SF)["snap"]
    assert works["eligible"] and not idle["eligible"]


def test_snap_zero_at_high_income():
    r = screen("IL", [adult("a", inc=120_000), adult("b", rel="spouse"), kid("c", 4), kid("d", 8)], COOK)
    assert r["snap"]["amount"] == 0 and not r["snap"]["eligible"]


def test_eitc_max_no_children():
    assert screen("CA", [adult("a", inc=9_000)], SF)["eitc"]["amount"] == 664


def test_eitc_max_one_child():
    assert screen("CA", [adult("a", inc=15_000), kid("c", 6)], SF)["eitc"]["amount"] == 4_427


def test_eitc_max_three_children():
    r = screen("CA", [adult("a", inc=20_000), kid("c", 3), kid("d", 7), kid("e", 10)], SF)
    assert r["eitc"]["amount"] == 8_231


def test_illinois_eitc_is_20_percent_of_federal():
    r = screen("IL", [adult("a", inc=20_000), kid("c", 3), kid("d", 7), kid("e", 10)], COOK)
    assert r["eitc"]["amount"] == 8_231
    assert r["il_eitc"]["amount"] == pytest.approx(0.20 * 8_231, abs=1)


def test_ctc_full_credit_married_two_children():
    r = screen("CA", [adult("a", inc=80_000), adult("b", rel="spouse"), kid("c", 5), kid("d", 8)], SF)
    assert r["ctc"]["amount"] == 4_400


def test_ctc_refundable_phase_in_low_earner():
    # No tax liability, so only the refundable part: 15% x ($10,000 - $2,500) = $1,125 (< $1,700 cap)
    assert screen("CA", [adult("a", inc=10_000), kid("c", 6)], SF)["ctc"]["amount"] == 1_125


@pytest.mark.parametrize("state,county", [("CA", SF), ("IL", COOK)])
def test_medicaid_expansion_adult(state, county):
    assert screen(state, [adult("a", inc=15_000)], county)["medicaid"]["eligible_people"] == ["a"]
    assert screen(state, [adult("a", inc=60_000)], county)["medicaid"]["eligible_people"] == []


def test_children_covered_when_parents_are_over_the_adult_limit():
    # Family of 3 at $50k is ~190% FPL: over 138% for the parent, under the CA children's limit (266%).
    r = screen("CA", [adult("a", inc=50_000), adult("b", rel="spouse"), kid("c", 5)], SF)
    covered = set(r["medicaid"]["eligible_people"]) | set(r["chip"]["eligible_people"])
    assert covered == {"c"}


def facts(result):
    return {f["variable"]: f for f in result["explain"]}


def test_explain_snap_high_income_fails_gross_test():
    r = screen("IL", [adult("a", inc=120_000), adult("b", rel="spouse"), kid("c", 4), kid("d", 8)], COOK)
    f = facts(r["snap"])
    assert f["meets_snap_gross_income_test"]["value"] is False
    assert f["snap_max_allotment"]["value"] == 994  # USDA FY2026, 4 people
    assert f["snap_max_allotment"]["label"] and f["snap_max_allotment"]["unit"] == "currency-USD"


def test_explain_eitc_maximum_matches_irs():
    r = screen("CA", [adult("a", inc=20_000), kid("c", 3), kid("d", 7), kid("e", 10)], SF)
    f = facts(r["eitc"])
    assert f["eitc_maximum"]["value"] == 8_231 and f["eitc_eligible"]["value"] is True


def test_explain_medicaid_income_level_vs_138_percent():
    # Expansion limit is 138% FPL: $15k is under it, $60k is over it, for one adult.
    low = facts(screen("CA", [adult("a", inc=15_000)], SF)["medicaid"])["medicaid_income_level"]["by_person"]["a"]
    high = facts(screen("CA", [adult("a", inc=60_000)], SF)["medicaid"])["medicaid_income_level"]["by_person"]["a"]
    assert low < 1.38 < high


def test_discount_eligible_even_when_bill_unknown():
    # Lifeline: income up to 135% FPL (47 CFR 54.409(a)(1)). The discount is capped by the
    # phone bill, which we haven't asked, so the amount is $0, but the household qualifies.
    r = screen("CA", [adult("a", inc=10_000, weekly_hours_worked=20)], SF)["lifeline"]
    assert r["eligible"] and r["amount"] == 0
    assert not screen("CA", [adult("a", inc=80_000)], SF)["lifeline"]["eligible"]


def test_wic_pregnant_low_income():
    assert screen("CA", [adult("a", inc=12_000, is_pregnant=True)], SF)["wic"]["eligible"]
