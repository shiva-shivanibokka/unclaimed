"""Research experiment E4 (docs/research-plan.md): why the E3 designs go wrong.

For the `tool` design (the model has the calculator but decides itself), each wrong program
on the results screen is traced to its cause by re-running the calculator on the last
household the model passed it:
  overrode       - the calculator said the opposite of what the model showed
  wrong facts    - the calculator agreed with the model on what it was given: the model asked
                   too little or passed the person's answers wrong
  no calculation - the model never ran the calculator successfully
Also counted for every design: conversations that never reached results, failed tool calls,
and the programs most often shown as "qualify" wrongly.

Run after eval/e3.py, like it (simulator env, from simulator/, engine up):
  uv run python ../eval/e4.py
Writes the E4 section of docs/research-results.md (e3.py rewrites from its own section on,
so rerun this after it).
"""

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from e3 import DATA, DESIGNS, OUT, _post, _write  # noqa: E402

CAUSES = ("overrode", "wrong facts", "no calculation")


def _calculated(row: dict) -> dict[str, bool] | None:
    """Eligibility per program from the last calculator call that worked, as the model saw it."""
    calls = [c for c in row["tool_calls"] if c["name"] == "calculate" and not c["failed"]]
    if not calls:
        return None
    r = _post("/calculate", calls[-1]["input"]["household"])
    return None if "error" in r else {p["id"]: p["eligible"] for p in r["programs"]}


def causes(rows: list[dict]) -> dict[str, Counter]:
    """For `tool` rows: the cause of each wrong "qualify" and each missed program."""
    out = {"false_qualify": Counter(), "missed": Counter()}
    for r in rows:
        if r["design"] != "tool" or "error" in r or not (r["false_qualify"] or r["missed"]):
            continue
        calc = _calculated(r)
        for field, shown in (("false_qualify", True), ("missed", False)):
            for p in r[field]:
                out[field]["no calculation" if calc is None else
                           "overrode" if calc.get(p, False) != shown else "wrong facts"] += 1
    return out


def section(rows: list[dict], by_cause: dict[str, dict[str, Counter]]) -> str:
    ok = [r for r in rows if "error" not in r]
    models = sorted({r["model"] for r in ok})
    lines = ["## E4: why the designs go wrong", "",
             "From the E3 rows (`eval/e4.py`). For the `tool` design, each wrong program is traced by re-running "
             "the calculator on the last household the model passed it: **overrode** = the calculator said the "
             "opposite of what the model showed; **wrong facts** = the calculator agreed with the model on what it "
             "was given (too few questions, or answers passed wrong); **no calculation** = it never ran.", "",
             "| Model | Wrong programs (tool design) | " + " | ".join(CAUSES) + " |", "|---|---|" + "---|" * len(CAUSES)]
    for model in models:
        c = by_cause[model]
        for field, label in (("false_qualify", "shown as \"qualify\", not eligible"), ("missed", "eligible, not shown")):
            lines.append(f"| `{model.split('.')[-1]}` | {label} ({sum(c[field].values())}) | "
                         + " | ".join(str(c[field][k]) for k in CAUSES) + " |")
    lines += ["", "| Model | Design | Didn't reach results | Failed tool calls | Programs most often shown as \"qualify\" wrongly |",
              "|---|---|---|---|---|"]
    for model in models:
        for design in DESIGNS:
            rs = [r for r in ok if r["model"] == model and r["design"] == design]
            if not rs:
                continue
            calls = [c for r in rs for c in r["tool_calls"]]
            top = Counter(p for r in rs for p in r["false_qualify"]).most_common(4)
            lines.append(f"| `{model.split('.')[-1]}` | {design} | {sum(1 for r in rs if not r['finished'])} of {len(rs)} | "
                         f"{sum(c['failed'] for c in calls)} of {len(calls)} | "
                         f"{', '.join(f'{p} ({n})' for p, n in top) or '-'} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    rows = [r for f in sorted(DATA.glob("e3-*.json")) for r in json.loads(f.read_text())]
    by_cause = {m: causes([r for r in rows if r["model"] == m]) for m in {r["model"] for r in rows}}
    out = section(rows, by_cause)
    text = OUT.read_text(encoding="utf-8")
    _write(OUT, text.split("## E4:")[0].rstrip() + "\n\n" + out)
    print(out)


if __name__ == "__main__":
    main()
