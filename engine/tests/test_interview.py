"""The benefits interview on top of the Question Engine. Rankings and flips, not dollar
amounts (from the planning research: engine/research/followup_sensitivity.py)."""

from unclaimed_engine.dictionary import load
from unclaimed_engine.household import Household
from unclaimed_engine.interview import next_question, open_questions

# Every other-income question answered "none", read from the dictionary's group.
NO_OTHER_INCOME = {q.id: 0 for q in load().questions
                   if q.group == load().question("self_employment_income").group and q.id != "employment_income"}


def la_family(income, **answers):
    return Household(state="CA", county="LOS_ANGELES_COUNTY_CA", as_of="2026-09-15", housing_tenure="RENTER",
                     rent=18_000, **answers, people=[
                         {"id": "mom", "relationship": "head", "age": 32, "employment_income": income,
                          "weekly_hours_worked": 40, **NO_OTHER_INCOME},
                         {"id": "k1", "relationship": "child", "age": 4, "social_security_dependents": 0,
                          "social_security_survivors": 0},
                         {"id": "k2", "relationship": "child", "age": 9, "social_security_dependents": 0,
                          "social_security_survivors": 0}])


def _ranking(h):
    """Every candidate's score (next_question shows only the top few)."""
    import question_engine as qe
    from unclaimed_engine import interview as iv
    open_ = iv.open_questions(h)
    keys = {(pid, q.id) for pid, q in open_}
    d = qe.decide(h, [iv._candidate(h, pid, q, keys) for pid, q in open_], iv._Calculator(),
                  flip_weight=iv.FLIP_WEIGHT, stop_below=iv.STOP_BELOW)
    return {s.candidate.key: s for s in d.ranked}


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
    job = ("mom", "has_job_health_insurance")
    assert _ranking(la_family(48_000))[job].flips == ("aca_ptc",)
    at32 = _ranking(la_family(32_000)).get(job)
    assert at32 is None or (not at32.flips and at32.swing == 0)
    # Child care flips SNAP at $48K and outranks savings (no SNAP asset test in CA).
    full = _ranking(la_family(48_000, has_job_health_insurance=False))
    assert "snap" in full[(None, "childcare_expenses")].flips
    assert full[(None, "childcare_expenses")].score > full[(None, "savings")].score


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


# Stage 3 adversarial review regressions.

def test_child_support_paid_high_reaches_the_snap_cutoff():
    # IL single at $32K: about $7K/yr of child support paid opens SNAP. The stop rule only
    # tries the what-if values, so the high must reach it (test_what_if_ranges checks all).
    from unclaimed_engine import batch
    q = load().question("child_support_paid")
    h = Household(state="IL", county="COOK_COUNTY_IL", as_of="2026-09-15", rent=12_000,
                  people=[{"id": "a", "relationship": "head", "age": 35, "employment_income": 32_000,
                           "weekly_hours_worked": 40}])
    low, high = batch.evaluate(h, [{("a", q.id): v} for v in q.what_if])
    assert not low["snap"][0] and high["snap"][0]


def test_declined_housing_still_asks_rent():
    h = Household(state="CA", county="LOS_ANGELES_COUNTY_CA", declined=["housing_tenure"],
                  people=[{"id": "a", "relationship": "head", "age": 35}])
    assert "rent" in {q.id for _, q in open_questions(h)}


def test_spouse_declining_status_makes_their_medicaid_conditional():
    from unclaimed_engine.interview import conditional_on_declined
    h = Household(state="IL", county="COOK_COUNTY_IL", as_of="2026-09-15", declined=["b.immigration_status"],
                  people=[{"id": "a", "relationship": "head", "age": 40, "employment_income": 25_000,
                           "weekly_hours_worked": 40, "immigration_status": "CITIZEN"},
                          {"id": "b", "relationship": "spouse", "age": 45},
                          {"id": "k", "relationship": "child", "age": 5}])
    assert "b.immigration_status" in conditional_on_declined(h).get("medicaid", [])


def test_split_zip_asks_the_county_first():
    h = Household(state="IL", zip="60011", people=[{"id": "a", "relationship": "head", "age": 33}])
    d = next_question(h)
    assert d["ask"]["question"] == "county" and set(d["ask"]["options"]) == {"COOK_COUNTY_IL", "LAKE_COUNTY_IL"}


def test_child_care_is_asked_for_a_disabled_teen():
    h = Household(state="CA", county="LOS_ANGELES_COUNTY_CA", people=[
        {"id": "a", "relationship": "head", "age": 40}, {"id": "b", "relationship": "child", "age": 15, "is_disabled": True}])
    assert "childcare_expenses" in {q.id for _, q in open_questions(h)}
