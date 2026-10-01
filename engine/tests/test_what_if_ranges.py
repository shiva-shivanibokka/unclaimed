"""The Question Engine tries each question at its two what-if values and stops when neither
flips a program. So the high what-if must be a realistic maximum: an answer above it that
flips eligibility would never be asked (e.g. $7,000 of child support paid opens SNAP;
a $6,000 high never shows it). This checks it across the coverage grid: no program's
eligibility differs between the high value and RANGE_FACTOR times it, wherever that
amount is plausible (slow: minutes).

Plausible: a yearly expense is at most half of earnings (no $48K of child support on
$60K of pay). Savings is a balance, so it's always checked. Questions asked
with a core question (other income) are always asked, so their what-ifs don't decide
when to stop and aren't checked.
"""

from datetime import date

import pytest

from unclaimed_engine import batch
from unclaimed_engine.coverage import grid
from unclaimed_engine.dictionary import load

RANGE_FACTOR = 2
INCOMES = range(0, 75_000, 5_000)
BALANCES = {"savings"}
EXPENSE_SHARE = 0.5


def scored_questions():
    """Numeric questions the Question Engine scores: not core, not grouped with a core one."""
    d = load()
    core_groups = {q.group for q in d.questions if q.core and q.group}
    return [q for q in d.questions if not q.core and q.group not in core_groups
            and q.answer["type"] in ("money", "number")]


def _plausible(q, amount: float, earnings: float) -> bool:
    return q.answer["type"] != "money" or q.id in BALANCES or amount <= earnings * EXPENSE_SHARE


@pytest.mark.slow
def test_no_flip_above_the_high_what_if():
    questions = scored_questions()
    beyond = []
    for label, h in grid(INCOMES):
        if label.endswith("/answered"):
            continue
        h = h.model_copy(update={"as_of": date(2026, 9, 15)})
        head = h.people[0].id
        earnings = sum(p.employment_income or 0 for p in h.people)
        checked = [q for q in questions if _plausible(q, q.what_if[1] * RANGE_FACTOR, earnings)]
        changes = []
        for q in checked:
            key = (head if q.entity == "person" else None, q.id)
            changes += [{key: q.what_if[1]}, {key: q.what_if[1] * RANGE_FACTOR}]
        results = batch.evaluate(h, changes)
        for n, q in enumerate(checked):
            at_high, above = results[2 * n], results[2 * n + 1]
            flipped = sorted(p for p in at_high if at_high[p][0] != above[p][0])
            if flipped:
                beyond.append(f"{label}: {q.id} {flipped}")
    assert not beyond, "high what-if is not a realistic maximum:\n" + "\n".join(beyond)
