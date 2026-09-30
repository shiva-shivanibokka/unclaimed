"""Household input, already in the engine's units (the MCP server converts from the
person's units: paycheck + frequency -> yearly income).

Every optional field is either known (a value) or unknown (None). Unknown fields are
not sent to PolicyEngine, which would silently fill in a default; we report those
defaults back as `assumptions` so nothing is assumed invisibly.
"""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, model_validator

Relationship = Literal["head", "spouse", "child"]
Immigration = Literal[
    "CITIZEN", "LEGAL_PERMANENT_RESIDENT", "REFUGEE", "ASYLEE", "DEPORTATION_WITHHELD",
    "CUBAN_HAITIAN_ENTRANT", "CONDITIONAL_ENTRANT", "PAROLED_ONE_YEAR", "UNDOCUMENTED",
    "DACA", "TPS",
]


class Person(BaseModel):
    id: str = Field(min_length=1, max_length=40)
    relationship: Relationship
    age: int = Field(ge=0, le=120)
    employment_income: float | None = Field(None, ge=0, description="Yearly, before taxes")
    self_employment_income: float | None = Field(None, description="Yearly net profit; may be negative")
    weekly_hours_worked: float | None = Field(None, ge=0, le=100, description="Flips SNAP for adults 18-64 without dependents (20 h/week rule)")
    is_pregnant: bool | None = None
    is_disabled: bool | None = None
    immigration_status: Immigration | None = None


class Household(BaseModel):
    state: Literal["CA", "IL"]
    county: str | None = Field(None, description="PolicyEngine county, e.g. SAN_FRANCISCO_COUNTY_CA")
    zip: str | None = Field(None, pattern=r"^\d{5}$")
    people: list[Person] = Field(min_length=1, max_length=12)
    rent: float | None = Field(None, ge=0, description="Yearly rent paid by the household")
    childcare_expenses: float | None = Field(None, ge=0, description="Yearly, out of pocket")
    as_of: date | None = Field(None, description="Screening date; defaults to today")

    @model_validator(mode="after")
    def _check(self) -> "Household":
        rel = [p.relationship for p in self.people]
        if rel.count("head") != 1:
            raise ValueError("exactly one person must be the head")
        if rel.count("spouse") > 1:
            raise ValueError("at most one spouse")
        ids = [p.id for p in self.people]
        if len(set(ids)) != len(ids):
            raise ValueError("person ids must be unique")
        if self.county and not self.county.endswith(f"_{self.state}"):
            raise ValueError(f"county {self.county} is not in {self.state}")
        return self
