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
# Test value per type: a realistic amount for money (yearly), the non-default for bools.
MONEY, COUNT = 6_000, 1
GROUP_KEYS = {"person": "people", "tax_unit": "tax_units", "spm_unit": "spm_units",
              "family": "families", "marital_unit": "marital_units", "household": "households"}


def test_value(var: str):
    meta = system.variables[var]
    t = meta.value_type.__name__
    if t == "bool":
        return not meta.default_value
    if t == "float":
        return MONEY
    if t == "int":
        return COUNT
    return None  # enums / strings: listed for manual review


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
    report = {v: {"test_value": test_value(v), "changes": {}} for v in inputs}
    sample = list(grid(INCOMES[:3]))
    for label, h in sample:
        base_sit, _ = build_situation(h, YEAR)
        scanned = [v for v in inputs if report[v]["test_value"] is not None]
        res = results(batch(base_sit, [None] + [(v, report[v]["test_value"]) for v in scanned]), h.state, len(scanned) + 1)
        base = res[0]
        for v, after in zip(scanned, res[1:]):
            changed = {p: {"from": base[p], "to": after[p]} for p in base if base[p] != after[p]}
            if changed:
                report[v]["changes"][label] = changed
        print(f"done {label}", flush=True)
    Path(out_path).write_text(json.dumps(report, indent=1))
    moving = sum(1 for r in report.values() if r["changes"])
    print(f"{len(inputs)} inputs scanned over {len(sample)} households; {moving} change a result -> {out_path}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
