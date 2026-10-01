"""Take-home pay -> pay before taxes, with PolicyEngine's own tax rules.

People often know only what lands in their account. Using that as pay before taxes would
understate income and could show a false "you qualify", so we find the pay before taxes
that leaves that take-home pay: the person's pay is tried at many amounts in one batched
simulation, and take-home = pay - the taxes that pay adds to their tax unit (others'
income held as answered).
"""

from datetime import date

import numpy as np
from policyengine_us import Simulation

from .batch import ID_STRIDE, apply, merge
from .calculate import build_situation, periods, resolve_county_for
from .household import Household

# What a paycheck withholds, as PolicyEngine variables (tax unit, yearly): payroll taxes
# (Social Security, Medicare, state payroll tax such as CA SDI) and income taxes before
# refundable credits (refundable credits come back at tax time, not in the paycheck).
WITHHELD = (
    "employee_payroll_tax",
    "employee_state_payroll_tax",
    "income_tax_before_refundable_credits",
    "state_income_tax_before_refundable_credits",
)
# Pay before taxes is searched between take-home and this multiple of it, in STEPS steps.
MAX_RATIO = 1.8
STEPS = 160


def gross_from_take_home(h: Household, person: str, take_home: float, question: str = "employment_income") -> float:
    """Yearly pay before taxes that leaves `take_home` (yearly) for `person`."""
    if take_home <= 0:
        return 0.0
    year, _ = periods(h.as_of or date.today())
    county, _ = resolve_county_for(h)
    grid = np.concatenate([[0.0], np.linspace(take_home, take_home * MAX_RATIO, STEPS)])
    situations = [build_situation(apply(h, {(person, question): float(g)}), year, county, id_offset=i * ID_STRIDE)[0]
                  for i, g in enumerate(grid)]
    sim = Simulation(situation=merge(situations))
    withheld = sum(sim.calculate(v, year, map_to="household") for v in WITHHELD)
    net = grid - (withheld - withheld[0])  # taxes this person's pay adds
    if net[-1] < take_home:
        raise ValueError("take-home pay is too high for these taxes; ask for pay before taxes")
    return float(np.interp(take_home, net[1:], grid[1:]))
