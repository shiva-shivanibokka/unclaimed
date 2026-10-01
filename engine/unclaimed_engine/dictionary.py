"""The dictionary (dictionary/dictionary.yaml): the single source for every fact the
engine can take in and for how every engine input our programs read is handled.

Buckets (each engine input in exactly one):
- questions: facts we ask. The API's household schema is generated from these.
- derived: set by our code from the household's structure or other answers.
- assumed: left at PolicyEngine's default (read from the engine, never retyped),
  with a plain-language statement for the results screen when it can change a result.
- out_of_scope: only relevant to places or programs we don't cover.

Validated against PolicyEngine at load, so a typo fails at startup, not as a silent default.
"""

from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any, Literal

import yaml
from policyengine_us.system import system

PATH = Path(__file__).resolve().parents[2] / "dictionary" / "dictionary.yaml"
ANSWER_TYPES = ("money", "bool", "number", "enum")
# Who could plausibly have an answer (never a program rule; see dictionary.yaml).
APPLIES_WHEN = {
    "person": {"age_min", "age_max", "non_citizen", "states"},
    "household": {"states"},
}
# Enum members that mean "not given" in the engine: never offered as an answer, so an
# unknown can't arrive disguised as a known value.
UNSET_OPTIONS = {"UNSPECIFIED", "UNKNOWN"}
# Where a household answer goes when its engine input is per person.
PLACEMENTS = {"head"}


@dataclass(frozen=True)
class Question:
    id: str
    entity: Literal["person", "household"]
    engine: tuple[str, ...]  # PolicyEngine inputs this answer sets (all get the same value)
    definition: str  # exactly what counts
    ask: str  # guidance for how the AI phrases it
    answer: dict[str, Any]  # type (money/bool/number/enum), min/max, engine units, person units
    cost: int  # 1 easy ... 5 sensitive
    what_if: tuple[Any, ...] = ()  # low/high values the Question Engine tries
    applies_when: dict[str, Any] = field(default_factory=dict)
    # Questions that must be answered first: question id -> allowed values, or None for
    # "answered with a non-zero / yes value" (e.g. hours only for someone with earnings).
    requires: dict[str, tuple[Any, ...] | None] = field(default_factory=dict)
    clarifiers: tuple[str, ...] = ()
    group: str | None = None  # asked together (e.g. "other_income")
    core: bool = False  # one of the five core questions
    # A household answer whose engine input is per person goes on this person ("head").
    # Required in that case, so no answer is ever placed on someone by accident.
    on_person: str | None = None

    @property
    def options(self) -> tuple[str, ...]:
        """Allowed values of an enum answer, read from the engine variable's enum."""
        return tuple(v.name for v in system.variables[self.engine[0]].possible_values if v.name not in UNSET_OPTIONS)


@dataclass(frozen=True)
class Group:
    """Assumed or out-of-scope inputs that share one reason."""
    engine: tuple[str, ...]
    reason: str
    statement: str | None = None  # shown to the person on the results screen


@dataclass(frozen=True)
class Dictionary:
    questions: tuple[Question, ...]
    derived: dict[str, str]  # engine variable -> how our code sets it
    assumed: tuple[Group, ...]
    out_of_scope: tuple[Group, ...]
    structure: dict[str, dict[str, str]]  # zip, county, people -> definition, ask
    groups: dict[str, dict[str, str]]  # group -> ask (how to ask the whole group as one question)

    def question(self, qid: str) -> Question:
        return next(q for q in self.questions if q.id == qid)

    def buckets(self) -> dict[str, str]:
        """engine variable -> bucket name. Raises if a variable is in two places."""
        seen: dict[str, str] = {}
        entries = [(v, f"question:{q.id}") for q in self.questions for v in q.engine]
        entries += [(v, "derived") for v in self.derived]
        entries += [(v, "assumed") for g in self.assumed for v in g.engine]
        entries += [(v, "out_of_scope") for g in self.out_of_scope for v in g.engine]
        for var, bucket in entries:
            if var in seen:
                raise ValueError(f"{var} is in both {seen[var]} and {bucket}")
            seen[var] = bucket
        return seen


def _check(d: Dictionary) -> None:
    for var in d.buckets():
        if var not in system.variables:
            raise ValueError(f"dictionary names {var}, which PolicyEngine doesn't have")
    ids = [q.id for q in d.questions]
    used = {q.group for q in d.questions if q.group}
    if d.groups and used != set(d.groups):
        raise ValueError(f"groups without phrasing or phrasing without questions: {used ^ set(d.groups)}")
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate question ids")
    for q in d.questions:
        if q.answer.get("type") not in ANSWER_TYPES:
            raise ValueError(f"{q.id}: answer.type must be one of {ANSWER_TYPES}")
        unknown = set(q.applies_when) - APPLIES_WHEN[q.entity]
        if unknown:
            raise ValueError(f"{q.id}: unknown applies_when keys {unknown}")
        if not all(isinstance(t, str) for t in (q.definition, q.ask, *q.clarifiers)):
            raise ValueError(f"{q.id}: phrasing must be text (a colon in YAML makes a mapping: quote it)")
        if not 1 <= q.cost <= 5:
            raise ValueError(f"{q.id}: cost must be 1-5")
        for r, allowed in q.requires.items():
            if r not in ids:
                raise ValueError(f"{q.id} requires unknown question {r}")
            other = d.question(r)
            if allowed and other.answer["type"] == "enum" and not set(allowed) <= set(other.options):
                raise ValueError(f"{q.id} requires {r} in {allowed}, not all valid options")
        for var in q.engine:
            engine_entity = system.variables[var].entity.key
            if q.entity == "person" and engine_entity != "person":
                raise ValueError(f"{q.id} is per person but {var} is per {engine_entity}")
            if q.entity == "household" and engine_entity == "person" and q.on_person not in PLACEMENTS:
                raise ValueError(f"{q.id} is per household but {var} is per person: set on_person")


def _requires(raw) -> dict[str, tuple[Any, ...] | None]:
    """`requires` as a list of ids (answered, non-zero) or a mapping id -> allowed values."""
    if isinstance(raw, list):
        return {r: None for r in raw}
    return {r: tuple(v) if v is not None else None for r, v in raw.items()}


class _StrictLoader(yaml.SafeLoader):
    """YAML keeps the last of two equal keys without a word; a dictionary entry with two
    `group:` lines would silently lose one. Refuse instead."""

    def construct_mapping(self, node, deep=False):
        keys = [self.construct_object(k, deep=deep) for k, _ in node.value]
        dupes = {k for k in keys if keys.count(k) > 1}
        if dupes:
            raise ValueError(f"duplicate keys {sorted(dupes)} at line {node.start_mark.line + 1}")
        return super().construct_mapping(node, deep=deep)


@cache
def load(path: Path = PATH) -> Dictionary:
    raw = yaml.load(path.read_text(encoding="utf-8"), Loader=_StrictLoader)
    d = Dictionary(
        questions=tuple(
            Question(**{**q, "engine": tuple(q["engine"]), "what_if": tuple(q.get("what_if", ())),
                        "requires": _requires(q.get("requires", {})), "clarifiers": tuple(q.get("clarifiers", ()))})
            for q in raw["questions"]
        ),
        derived=dict(raw["derived"]),
        assumed=tuple(Group(**{**g, "engine": tuple(g["engine"])}) for g in raw["assumed"]),
        out_of_scope=tuple(Group(**{**g, "engine": tuple(g["engine"])}) for g in raw["out_of_scope"]),
        structure={k: dict(v) for k, v in raw.get("structure", {}).items()},
        groups={k: dict(v) for k, v in raw.get("groups", {}).items()},
    )
    _check(d)
    return d
