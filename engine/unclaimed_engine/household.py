"""Household input, already in the engine's units (the MCP server converts from the
person's units: paycheck + frequency -> yearly income).

Only the household's structure is defined here (who is in it, how they're related,
where they live, when). Every fact about them is a field generated from the dictionary
(dictionary/dictionary.yaml), the single source for what we can be told. Each such field
is either known (a value) or unknown (None); unknowns are reported back as assumptions.

Allowed values (immigration statuses, counties) come from PolicyEngine itself.
"""

from datetime import date
from typing import Any, Literal

from policyengine_us.system import system
from pydantic import BaseModel, Field, create_model, model_validator

from .dictionary import Question, load
from .programs import SUPPORTED_STATES

Relationship = Literal["head", "spouse", "child"]
COUNTIES = frozenset(c.name for c in system.variables["county"].possible_values)
# Our limits. Money: sane bounds so absurd values can't reach the engine (1e300 -> NaN).
MAX_MONEY = 10_000_000
# Screening dates: last year through next year, the range our official-figure tests
# cover. Outside it the engine errors (no parameters) or silently extrapolates.
AS_OF_YEARS_AROUND_TODAY = 1


def _field(q: Question) -> tuple[Any, Any]:
    """Pydantic field for a dictionary question: optional, typed and bounded per its answer spec."""
    a = q.answer
    if a["type"] == "bool":
        return bool | None, Field(None, description=q.definition)
    if a["type"] == "enum":
        return Literal[q.options] | None, Field(None, description=q.definition)
    low = a.get("min", -MAX_MONEY if a.get("negative") else 0)
    high = a.get("max", MAX_MONEY)
    return float | None, Field(None, ge=low, le=high, description=f"{q.definition} ({a['unit']})")


def _answers(entity: str) -> dict[str, tuple[Any, Any]]:
    return {q.id: _field(q) for q in load().questions if q.entity == entity}


class _PersonBase(BaseModel):
    id: str = Field(min_length=1, max_length=40)
    relationship: Relationship
    age: int = Field(ge=0, le=120)


class _HouseholdBase(BaseModel):
    state: Literal[SUPPORTED_STATES]
    county: str | None = Field(None, description="PolicyEngine county, e.g. SAN_FRANCISCO_COUNTY_CA")
    zip: str | None = Field(None, pattern=r"^\d{5}$", description="Used to find the county when county is unknown")
    as_of: date | None = Field(None, description="Screening date; defaults to today")
    declined: list[str] = Field(
        default_factory=list,
        description="Questions the person chose not to answer: 'question_id' for household questions, "
                    "'person_id.question_id' for person questions. Calculated as unknown, reported as declined.")

    @model_validator(mode="after")
    def _check(self):
        people = self.people
        rel = [p.relationship for p in people]
        if rel.count("head") != 1:
            raise ValueError("exactly one person must be the head")
        if rel.count("spouse") > 1:
            raise ValueError("at most one spouse")
        ids = [p.id for p in people]
        if len(set(ids)) != len(ids):
            raise ValueError("person ids must be unique")
        if self.county and (self.county not in COUNTIES or not self.county.endswith(f"_{self.state}")):
            raise ValueError(f"{self.county} is not a county in {self.state}")
        head = next(p for p in people if p.relationship == "head")
        if any(p.relationship == "child" and p.age >= head.age for p in people):
            raise ValueError("a child must be younger than the head")
        if self.as_of and abs(self.as_of.year - date.today().year) > AS_OF_YEARS_AROUND_TODAY:
            raise ValueError(f"as_of must be within {AS_OF_YEARS_AROUND_TODAY} year of today")
        questions = {q.id: q for q in load().questions}
        by_id = {p.id: p for p in people}
        if len(set(self.declined)) != len(self.declined):
            raise ValueError("declined: duplicate entries")
        for item in self.declined:
            pid, dot, qid = item.rpartition(".")
            q = questions.get(qid)
            if not q or (dot and not pid) or (q.entity == "person") != bool(pid) or (pid and pid not in by_id):
                raise ValueError(f"declined: {item!r} is not a question for this household")
            if getattr(by_id[pid] if pid else self, qid) is not None:
                raise ValueError(f"declined: {item!r} also has an answer")
        return self


Person = create_model("Person", __base__=_PersonBase, **_answers("person"))
Household = create_model(
    "Household", __base__=_HouseholdBase,
    people=(list[Person], Field(min_length=1, max_length=12)),
    **_answers("household"),
)
