"""The dictionary is the single source for engine inputs: structure and consistency checks.
The full coverage check (every input the programs read is classified) is in
test_coverage.py, which traces the engine and is slower."""

from unclaimed_engine.calculate import DERIVERS
from unclaimed_engine.dictionary import load
from unclaimed_engine.household import Household, Person, _HouseholdBase, _PersonBase


def test_every_derived_input_has_code_and_vice_versa():
    assert set(DERIVERS) == set(load().derived)


def test_no_input_in_two_buckets():
    load().buckets()  # raises on duplicates


def test_api_schema_is_generated_from_the_dictionary():
    d = load()
    # Everything beyond the structural base models comes from the dictionary.
    person_fields = set(Person.model_fields) - set(_PersonBase.model_fields)
    household_fields = set(Household.model_fields) - set(_HouseholdBase.model_fields) - {"people"}
    assert person_fields == {q.id for q in d.questions if q.entity == "person"}
    assert household_fields == {q.id for q in d.questions if q.entity == "household"}


def test_household_answer_on_a_person_input_needs_a_placement(tmp_path):
    import pytest
    bad = tmp_path / "d.yaml"
    bad.write_text("""questions:
  - {id: x, entity: household, engine: [pre_subsidy_rent], definition: d, ask: a,
     answer: {type: money, unit: u, person_units: [year]}, what_if: [0, 1], cost: 1}
derived: {}
assumed: []
out_of_scope: []
""")
    with pytest.raises(ValueError, match="on_person"):
        load.__wrapped__(bad)


def test_questions_are_complete():
    for q in load().questions:
        assert q.definition and q.ask, q.id
        assert len(q.what_if) == 2, f"{q.id}: what_if needs a low and a high value"
        if q.answer["type"] == "money":
            assert q.answer.get("unit") and q.answer.get("person_units"), q.id


def test_structure_phrasing_covers_the_household_fields_we_ask():
    # ZIP, county and people are asked like questions; their phrasing lives in the dictionary.
    s = load().structure
    assert set(s) == {"zip", "county", "people"} and set(s) <= set(Household.model_fields)
    assert all(v["definition"] and v["ask"] for v in s.values())


def test_phrasing_states_no_program_rules():
    # The AI repeats phrasing to people, so it must not carry a rule or threshold (an age
    # limit, a work-hours rule, a waiting period) that can go stale: those live in
    # PolicyEngine. Numbers allowed only in names and calendar facts.
    import re
    allowed = ("401(k)", "Section 8", "3-month", "4 quarters")
    d = load()
    texts = [(q.id, t) for q in d.questions for t in (q.definition, q.ask, *q.clarifiers)]
    texts += [("statement", g.statement) for g in d.assumed if g.statement]
    texts += [(k, t) for k, v in d.structure.items() for t in v.values()]
    texts += [(k, v["ask"]) for k, v in d.groups.items()]
    for qid, text in texts:
        for name in allowed:
            text = text.replace(name, "")
        assert not re.search(r"\d", text), f"{qid}: {text}"


def test_gates_are_plausibility_not_program_rules():
    # applies_when may only say who could have an answer. An age that equals one of
    # PolicyEngine's eligibility ages is a copied program rule (SNAP elderly age, student ages).
    from policyengine_us.system import system
    p = system.parameters
    rule_ages = {p.gov.usda.elderly_age_threshold("2026-01-01")}
    rule_ages |= {b.threshold("2026-01-01") for b in p.gov.usda.snap.student.age_threshold.brackets}
    rule_ages -= {0, 18}  # birth and adulthood: our plausibility lines, not program rules
    for q in load().questions:
        ages = {v for k, v in q.applies_when.items() if k.startswith("age_")}
        assert not ages & rule_ages, f"{q.id}: {ages & rule_ages}"


def test_duplicate_keys_are_refused(tmp_path):
    import pytest
    bad = tmp_path / "d.yaml"
    bad.write_text("questions: []\nderived: {}\nderived: {}\nassumed: []\nout_of_scope: []\n")
    with pytest.raises(ValueError, match="duplicate"):
        load.__wrapped__(bad)
