"""Every PolicyEngine input our programs read is classified in the dictionary (asked,
derived, assumed, or out of scope), so nothing is silently defaulted without a decision.
Traces the engine over the coverage grid (slow: about two minutes)."""

import pytest

from unclaimed_engine.coverage import grid, traced_inputs
from unclaimed_engine.dictionary import load


@pytest.mark.slow
def test_every_input_read_is_classified():
    read = traced_inputs(grid(incomes=(0, 35_000)))
    unclassified = sorted(set(read) - set(load().buckets()))
    assert not unclassified, f"{len(unclassified)} inputs read but not in the dictionary: {unclassified}"
