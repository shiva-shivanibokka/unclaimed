"""Household input, already in the engine's units (the MCP server converts from the
person's units: paycheck + frequency -> yearly income).

Every optional field is either known (a value) or unknown (None). Unknown fields are
not sent to PolicyEngine, which would silently fill in a default; we report those
defaults back as `assumptions` so nothing is assumed invisibly.

Allowed values (immigration statuses, counties) come from PolicyEngine itself, the
single source of truth, so a PolicyEngine upgrade can't leave a stale copy here.
"""

from datetime import date
from typing import Literal

from policyengine_us.system import system
from pydantic import BaseModel, Field, model_validator

from .programs import SUPPORTED_STATES

Relationship = Literal["head", "spouse", "child"]
Immigration = Literal[tuple(s.name for s in system.variables["immigration_status"].possible_values)]
COUNTIES = frozenset(c.name for c in system.variables["county"].possible_values)
# Our limits. Money: sane bounds so absurd values can't reach the engine (1e300 -> NaN).
MAX_MONEY = 10_000_000
# Screening dates: last year through next year, the range our official-figure tests
# cover. Outside it the engine errors (no parameters) or silently extrapolates.
AS_OF_YEARS_AROUND_TODAY = 1


class Person(BaseModel):
    id: str = Field(min_length=1, max_length=40)
    relationship: Relationship
    age: int = Field(ge=0, le=120)
    employment_income: float | None = Field(None, ge=0, le=MAX_MONEY, description="Yearly, before taxes")
    self_employment_income: float | None = Field(None, ge=-MAX_MONEY, le=MAX_MONEY, description="Yearly net profit; may be negative")
    weekly_hours_worked: float | None = Field(None, ge=0, le=100, description="Flips SNAP for adults 18-64 without dependents (20 h/week rule)")
    is_pregnant: bool | None = None
    is_disabled: bool | None = None
    immigration_status: Immigration | None = None


class Household(BaseModel):
    state: Literal[SUPPORTED_STATES]
    county: str | None = Field(None, description="PolicyEngine county, e.g. SAN_FRANCISCO_COUNTY_CA")
    zip: str | None = Field(None, pattern=r"^\d{5}$", description="Used to find the county when county is unknown")
    people: list[Person] = Field(min_length=1, max_length=12)
    rent: float | None = Field(None, ge=0, le=MAX_MONEY, description="Yearly rent paid by the household")
    childcare_expenses: float | None = Field(None, ge=0, le=MAX_MONEY, description="Yearly, out of pocket")
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
        if self.county and (self.county not in COUNTIES or not self.county.endswith(f"_{self.state}")):
            raise ValueError(f"{self.county} is not a county in {self.state}")
        head = next(p for p in self.people if p.relationship == "head")
        if any(p.relationship == "child" and p.age >= head.age for p in self.people):
            raise ValueError("a child must be younger than the head")
        if self.as_of and abs(self.as_of.year - date.today().year) > AS_OF_YEARS_AROUND_TODAY:
            raise ValueError(f"as_of must be within {AS_OF_YEARS_AROUND_TODAY} year of today")
        return self
