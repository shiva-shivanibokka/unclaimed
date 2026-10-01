"""Which engine inputs can change a result? For every input our programs read (from
trace_inputs.py's output), set it to a realistic non-default value in a sample of
households and record which programs' amounts or eligibility change.

This is the evidence behind the dictionary's buckets: an input that changes results for
real households must be asked, or assumed out loud; one that never does can be assumed
silently.

Run: uv run python scripts/sensitivity_scan.py trace.json out.json   (trace.json from trace_inputs.py)
"""

import copy
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from policyengine_us import Simulation  # noqa: E402
from policyengine_us.system import system  # noqa: E402

from unclaimed_engine.calculate import build_situation, period_for, periods  # noqa: E402
from unclaimed_engine.coverage import INCOMES, grid  # noqa: E402
from unclaimed_engine.programs import PROGRAMS  # noqa: E402

YEAR, MONTH = periods(date.today())
# Test values per type, in both directions from the default: zero and realistic amounts
# for numbers, the other value for bools, every option for enums. A value equal to the
# engine's default is skipped (it can't change anything).
NUMBERS = {"float": (0, 2, 6_000), "int": (0, 1, 10, 40)}
GROUP_KEYS = {e.key: e.plural for e in system.entities}


def test_values(var: str) -> list:
    meta = system.variables[var]
    t = meta.value_type.__name__
    if t == "bool":
        values = [True, False]
    elif t in NUMBERS:
        values = list(NUMBERS[t])
    elif t == "Enum":
        values = [v.name for v in meta.possible_values]
    else:
        return []  # strings (ids, FIPS): structural, handled by derivers
    default = getattr(meta.default_value, "name", meta.default_value)
    return [v for v in values if v != default]


def batch(situation: dict, variants: list[tuple[str, object] | None]) -> dict:
    """One simulation holding a copy of the household per variant (None = unchanged), so
    PolicyEngine computes every what-if in one vectorized pass instead of one run each."""
    big = {g: {} for g in situation}
    for i, variant in enumerate(variants):
        rename = {pid: f"c{i}_{pid}" for pid in situation["people"]}
        for g, entities in situation.items():
            for name, entity in entities.items():
                e = copy.deepcopy(entity)
                if "members" in e:
                    e["members"] = [rename[m] for m in e["members"]]
                big[g][rename[name] if g == "people" else f"c{i}_{name}"] = e
        if variant:
            var, value = variant
            meta = system.variables[var]
            period = MONTH if meta.definition_period == "month" else YEAR
            for name, e in big[GROUP_KEYS[meta.entity.key]].items():
                if name.startswith(f"c{i}_"):
                    e[var] = {period: value}
    return big


def results(situation: dict, state: str, n: int) -> list[dict]:
    """Per copy: {program: (amount, eligible)}."""
    sim = Simulation(situation=situation)
    out = [{} for _ in range(n)]
    for p in PROGRAMS:
        if state not in p.states:
            continue
        amounts = sim.calculate(p.variable, period_for(p.variable, YEAR, MONTH), map_to="household")
        flags = (sim.calculate(p.eligibility, period_for(p.eligibility, YEAR, MONTH), map_to="household") > 0
                 if p.eligibility else amounts > 0)
        for i in range(n):
            out[i][p.id] = (round(float(amounts[i]), 2), bool(flags[i]))
    return out


def main(trace_path: str, out_path: str) -> None:
    # Inputs not already asked or derived: the ones whose handling the scan informs.
    inputs = [r["variable"] for r in json.loads(Path(trace_path).read_text())
              if not (r["bucket"] or "").startswith(("question:", "derived"))]
    report = {v: {"test_values": test_values(v), "changes": {}} for v in inputs}
    sample = list(grid(INCOMES[:3]))
    for label, h in sample:
        base_sit, _ = build_situation(h, YEAR)
        variants = [(v, x) for v in inputs for x in report[v]["test_values"]]
        res = results(batch(base_sit, [None, *variants]), h.state, len(variants) + 1)
        base = res[0]
        for (v, x), after in zip(variants, res[1:]):
            changed = {p: {"from": base[p], "to": after[p]} for p in base if base[p] != after[p]}
            if changed:
                report[v]["changes"].setdefault(label, {})[str(x)] = changed
        print(f"done {label}", flush=True)
    Path(out_path).write_text(json.dumps(report, indent=1))
    moving = sum(1 for r in report.values() if r["changes"])
    print(f"{len(inputs)} inputs scanned over {len(sample)} households; {moving} change a result -> {out_path}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
