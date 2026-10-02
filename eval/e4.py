"""Research experiment E4 (docs/research-plan.md): why the E3 designs go wrong.

For the `tool` design (the model has the calculator but decides itself), each wrong program
on the results screen is traced to its cause by re-running the calculator on the last
household the engine accepted from the model before it showed results:
  overrode       - the calculator said the opposite of what the model showed
  wrong facts    - the calculator agreed with the model on what it was given: facts missing
                   or passed wrong (not told apart)
  no calculation - no calculation the engine accepted
  no results     - the conversation never showed results (it missed everything)
Also counted for every design: conversations that never reached results, failed tool calls,
and the programs most often shown as "qualify" wrongly.

Run after eval/e3.py, like it (simulator env, from simulator/, engine up):
  uv run python ../eval/e4.py
Writes the E4 section of docs/research-results.md (e3.py rewrites from its own section on,
so rerun this after it).
"""

import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from e3 import DATA, DESIGNS, OUT, _post, _write  # noqa: E402

CAUSES = ("overrode", "wrong facts", "no calculation", "no results")


def _calculated(row: dict) -> dict[str, bool] | None:
    """Eligibility per program from the last calculator call the engine accepted before the
    results were shown: what the model was looking at. (The calculate tool hands engine
    errors back as a result, so a refused call isn't marked failed; re-running finds it.)"""
    calls = [c for c in row["tool_calls"] if c["name"] in ("calculate", "show_results")]
    shown = max((i for i, c in enumerate(calls) if c["name"] == "show_results"), default=len(calls))
    for c in reversed(calls[:shown]):
        if c["name"] == "calculate" and not c["failed"]:
            r = _post("/calculate", c["input"]["household"])
            if "error" not in r:
                return {p["id"]: p["eligible"] for p in r["programs"]}
    return None


def causes(rows: list[dict]) -> dict[str, Counter]:
    """For `tool` rows: the cause of each wrong "qualify" and each missed program. A
    conversation that never showed results missed everything: "no results"."""
    out = {"false_qualify": Counter(), "missed": Counter()}
    for r in rows:
        if r["design"] != "tool" or "error" in r or not (r["false_qualify"] or r["missed"]):
            continue
        if not r["finished"]:
            out["missed"]["no results"] += len(r["missed"])
            continue
        calc = _calculated(r)
        for field, shown in (("false_qualify", True), ("missed", False)):
            for p in r[field]:
                assert calc is None or p in calc, f"{r['id']}: {p} not in the calculator's output"
                out[field]["no calculation" if calc is None else
                           "overrode" if calc[p] != shown else "wrong facts"] += 1
    return out


def refused(rows: list[dict]) -> tuple[int, int]:
    """Tool calls refused: marked failed (our MCP server's errors), or, for the calculator,
    an engine error handed back as a result (found by re-running it)."""
    calls = [c for r in rows for c in r["tool_calls"]]
    bad = sum(1 for c in calls if c["failed"] or (c["name"] == "calculate" and "error" in _post("/calculate", c["input"]["household"])))
    return bad, len(calls)


def _commit() -> str:
    return subprocess.run(["git", "describe", "--always", "--dirty"], cwd=DATA, capture_output=True, text=True).stdout.strip()


def section(rows: list[dict], by_cause: dict[str, dict[str, Counter]]) -> str:
    ok = [r for r in rows if "error" not in r]
    models = sorted({r["model"] for r in ok})
    lines = ["## E4: why the designs go wrong", "",
             f"From the E3 rows (`eval/e4.py`, calculator re-run on `{_commit()}`). For the `tool` design, each wrong "
             "program is traced by re-running the calculator on the last household the engine accepted from the model "
             "before it showed results: **overrode** = the calculator said the opposite of what the model showed; "
             "**wrong facts** = the calculator agreed with the model on what it was given (facts missing or passed "
             "wrong: not told apart); **no calculation** = no accepted calculation; **no results** = the conversation "
             "never showed results, so it missed everything. Refused tool calls: errors from our MCP server, or an "
             "engine error handed back by the calculator.", "",
             "| Model | Wrong programs (tool design) | " + " | ".join(CAUSES) + " |", "|---|---|" + "---|" * len(CAUSES)]
    for model in models:
        c = by_cause[model]
        for field, label in (("false_qualify", "shown as \"qualify\", not eligible"), ("missed", "eligible, not shown")):
            lines.append(f"| `{model.split('.')[-1]}` | {label} ({sum(c[field].values())}) | "
                         + " | ".join(str(c[field][k]) for k in CAUSES) + " |")
    lines += ["", "| Model | Design | Didn't reach results | Refused tool calls | Programs most often shown as \"qualify\" wrongly |",
              "|---|---|---|---|---|"]
    for model in models:
        for design in DESIGNS:
            rs = [r for r in ok if r["model"] == model and r["design"] == design]
            if not rs:
                continue
            bad, n = refused(rs)
            top = Counter(p for r in rs for p in r["false_qualify"]).most_common(4)
            lines.append(f"| `{model.split('.')[-1]}` | {design} | {sum(1 for r in rs if not r['finished'])} of {len(rs)} | "
                         f"{bad} of {n} | "
                         f"{', '.join(f'{p} ({k})' for p, k in top) or '-'} |")
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
