"""Many households in one PolicyEngine simulation. The engine is vectorized, so hundreds
of what-if variants cost little more than one household; running them one by one is
~100x slower. Used by the Question Engine and the sensitivity scan."""

import copy
from datetime import date

from policyengine_us import Simulation

from .calculate import build_situation, periods, program_values, resolve_county_for
from .household import Household
from .programs import PROGRAMS

ID_STRIDE = 100  # tax unit IDs per copy; each copy's IDs start at i * ID_STRIDE + 1


def merge(situations: list[dict]) -> dict:
    """One situation holding every given household; copy i's people and units get a
    "v{i}_" prefix, in order, so results map back by household index."""
    big: dict[str, dict] = {}
    for i, situation in enumerate(situations):
        for group, entities in situation.items():
            for name, entity in entities.items():
                e = copy.deepcopy(entity)
                if "members" in e:
                    e["members"] = [f"v{i}_{m}" for m in e["members"]]
                big.setdefault(group, {})[f"v{i}_{name}"] = e
    return big


def apply(h: Household, change: dict) -> Household:
    """The household with answers changed: keys are (person id, question id) for person
    questions, (None, question id) for household questions."""
    household = {qid: v for (pid, qid), v in change.items() if pid is None}
    people = [p.model_copy(update={qid: v for (pid, qid), v in change.items() if pid == p.id}) for p in h.people]
    return h.model_copy(update={**household, "people": people})


def outcomes(situation: dict, state: str, year: str, month: str, n: int) -> list[dict[str, tuple[bool, float]]]:
    """Per household in a merged situation: program id -> (eligible, monthly value)."""
    sim = Simulation(situation=situation)
    out: list[dict] = [{} for _ in range(n)]
    for p in PROGRAMS:
        if state in p.states:
            monthly, flags = program_values(sim, p, year, month)
            for i in range(n):
                out[i][p.id] = (bool(flags[i]), float(monthly[i]))
    return out


def evaluate(h: Household, changes: list[dict]) -> list[dict[str, tuple[bool, float]]]:
    """Outcomes of the household under each change (an empty change = as is), in one simulation."""
    year, month = periods(h.as_of or date.today())
    county, _ = resolve_county_for(h)
    situations = [build_situation(apply(h, c), year, county, id_offset=i * ID_STRIDE)[0]
                  for i, c in enumerate(changes)]
    return outcomes(merge(situations), h.state, year, month, len(changes))
