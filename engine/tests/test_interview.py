"""The benefits interview on top of the Question Engine. Rankings and flips, not dollar
amounts (from the planning research: engine/research/followup_sensitivity.py)."""

from unclaimed_engine.household import Household
from unclaimed_engine.interview import next_question, open_questions

NO_OTHER_INCOME = {q: 0 for q in (
    "self_employment_income", "unemployment_compensation", "social_security_retirement",
    "social_security_disability", "social_security_survivors", "social_security_dependents",
    "child_support_received", "alimony_income", "pension_income", "retirement_withdrawals",
    "interest_dividends", "rental_income", "veterans_benefits", "workers_compensation",
    "disability_benefits", "ca_state_disability_insurance", "general_assistance")}


def la_family(income, **answers):
    return Household(state="CA", county="LOS_ANGELES_COUNTY_CA", as_of="2026-09-15", housing_tenure="RENTER",
                     rent=18_000, **answers, people=[
                         {"id": "mom", "relationship": "head", "age": 32, "employment_income": income,
                          "weekly_hours_worked": 40, **NO_OTHER_INCOME},
                         {"id": "k1", "relationship": "child", "age": 4, "social_security_dependents": 0,
                          "social_security_survivors": 0},
                         {"id": "k2", "relationship": "child", "age": 9, "social_security_dependents": 0,
                          "social_security_survivors": 0}])


def ranked(d):
    return {(c["person"], c["question"]): c for c in d["top_candidates"]}


def test_core_questions_come_first_in_order():
    h = Household(state="IL", county="COOK_COUNTY_IL", people=[{"id": "a", "relationship": "head", "age": 30}])
    d = next_question(h)
    assert d["core"] and d["ask"]["question"] == "employment_income"


def test_other_income_is_asked_once_for_everyone():
    h = Household(state="CA", county="LOS_ANGELES_COUNTY_CA", people=[
        {"id": "a", "relationship": "head", "age": 40, "employment_income": 20_000},
        {"id": "b", "relationship": "spouse", "age": 70, "employment_income": 0}])
    d = next_question(h)
    asked = {(x["person"], x["question"]) for x in [d["ask"], *d["together"]]}
    assert ("b", "social_security_retirement") in asked and ("a", "unemployment_compensation") in asked


def test_rent_only_for_renters_mortgage_only_for_owners():
    h = Household(state="IL", county="COOK_COUNTY_IL", housing_tenure="OWNER_WITH_MORTGAGE",
                  people=[{"id": "a", "relationship": "head", "age": 50}])
    open_ = {q.id for _, q in open_questions(h)}
    assert "mortgage_payments" in open_ and "rent" not in open_


def test_child_care_matters_at_48k_and_job_insurance_only_above_medicaid():
    # Research (CA, LA, parent + kids 4 and 9): at $48K child care flips SNAP; job insurance
    # flips the ACA credit at $48K but changes nothing at $32K (the parent is on Medi-Cal).
    at48 = ranked(next_question(la_family(48_000)))
    assert at48[("mom", "has_job_health_insurance")]["flips"] == ["aca_ptc"]
    d32 = next_question(la_family(32_000))
    assert ("mom", "has_job_health_insurance") not in ranked(d32)
    d48 = next_question(la_family(48_000, has_job_health_insurance=False, electricity_bill=1_200, gas_bill=600,
                                  receives_tanf=False))
    assert "childcare_expenses" in {c["question"] for c in d48["top_candidates"]}


def test_stops_when_everything_is_known():
    h = la_family(48_000)
    while not (d := next_question(h))["stop"]:
        keys = [(d["ask"]["person"], d["ask"]["question"])] + [(x["person"], x["question"]) for x in d["together"]]
        hh = {q: _zero(q) for p, q in keys if p is None}
        people = [p.model_copy(update={q: _zero(q) for pid, q in keys if pid == p.id}) for p in h.people]
        h = h.model_copy(update={**hh, "people": people})
    assert d["stop"] and not d["ask"]


def _zero(qid):
    from unclaimed_engine.dictionary import load
    q = load().question(qid)
    return {"bool": False, "enum": q.what_if[0]}.get(q.answer["type"], 0)


def test_declined_answer_that_decides_eligibility_makes_it_conditional():
    # Declined immigration status: federal EITC depends on it (SSN valid for work), so the
    # result is "if ...", not a flat "you qualify".
    from unclaimed_engine.interview import conditional_on_declined
    h = Household(state="CA", county="LOS_ANGELES_COUNTY_CA", as_of="2026-09-15", declined=["a.immigration_status"],
                  people=[{"id": "a", "relationship": "head", "age": 33, "employment_income": 25_000,
                           "weekly_hours_worked": 40}, {"id": "b", "relationship": "child", "age": 4}])
    assert "a.immigration_status" in conditional_on_declined(h).get("eitc", [])
