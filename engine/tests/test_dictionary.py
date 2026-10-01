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
