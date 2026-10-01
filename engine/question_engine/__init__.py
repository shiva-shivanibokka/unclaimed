"""Question Engine: decide which question to ask next by testing which unknown fact would
change the answer the most.

Domain-free: it knows nothing about benefits, mortgages or any rules engine. You give it
- candidates: the questions still worth considering, each with a low and a high value to
  try and a cost (how burdensome or sensitive it is to ask), and
- a calculator: runs your rules for many variants of the current state at once and
  returns, per variant, each outcome's (eligible, value).

For each candidate it compares the outcomes at its low and high values: how many outcomes
flip between yes and no, and how much value moves. The score is
    (flip_weight * flips + swing) / cost
and the top candidate is asked, unless nothing would flip and no value moves by at least
`stop_below`, in which case the interview can stop: no remaining question would change the
answer enough to be worth asking.
"""

from dataclasses import dataclass, field
from typing import Any, Hashable, Mapping, Protocol, Sequence

Outcome = tuple[bool, float]  # (eligible, value)
Outcomes = Mapping[str, Outcome]  # outcome id -> Outcome
Change = Mapping[Hashable, Any]  # candidate key -> value to try


class Calculator(Protocol):
    def evaluate(self, state: Any, changes: Sequence[Change]) -> list[Outcomes]:
        """Outcomes for the state with each change applied (an empty change = the state as is).
        Batch them: this is called once per decision with every variant."""


@dataclass(frozen=True)
class Candidate:
    key: Hashable  # what to change in the state, e.g. ("person-1", "income")
    low: Any
    high: Any
    cost: float = 1.0
    together: tuple[Hashable, ...] = ()  # asked in the same breath (e.g. all "other income" kinds)


@dataclass(frozen=True)
class Scored:
    candidate: Candidate
    flips: tuple[str, ...]  # outcomes whose eligibility differs between low and high
    swing: float  # total |value(high) - value(low)| across outcomes
    score: float


@dataclass(frozen=True)
class Decision:
    ask: Candidate | None  # None: stop, nothing left would change the answer enough
    ranked: tuple[Scored, ...] = field(default_factory=tuple)

    @property
    def stop(self) -> bool:
        return self.ask is None


def score(candidates: Sequence[Candidate], low: Sequence[Outcomes], high: Sequence[Outcomes],
          flip_weight: float) -> list[Scored]:
    ranked = []
    for c, lo, hi in zip(candidates, low, high):
        ids = lo.keys() & hi.keys()
        flips = tuple(sorted(i for i in ids if lo[i][0] != hi[i][0]))
        swing = sum(abs(hi[i][1] - lo[i][1]) for i in ids)
        ranked.append(Scored(c, flips, swing, (flip_weight * len(flips) + swing) / c.cost))
    return sorted(ranked, key=lambda s: -s.score)


def decide(state: Any, candidates: Sequence[Candidate], calculator: Calculator, *,
           flip_weight: float, stop_below: float) -> Decision:
    """The next question to ask, or stop. One batched calculator call: every candidate's
    low and high variants together."""
    if not candidates:
        return Decision(ask=None)
    changes = [{c.key: c.low} for c in candidates] + [{c.key: c.high} for c in candidates]
    results = calculator.evaluate(state, changes)
    n = len(candidates)
    ranked = score(candidates, results[:n], results[n:], flip_weight)
    # Stop only if no candidate flips anything (a costly question can rank low and still
    # flip an outcome) and no value moves enough.
    if not any(s.flips for s in ranked) and all(s.swing < stop_below for s in ranked):
        return Decision(ask=None, ranked=tuple(ranked))
    return Decision(ask=ranked[0].candidate, ranked=tuple(ranked))
