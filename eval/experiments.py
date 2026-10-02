"""Research experiments E1 and E2 (docs/research-plan.md), with the Tier A + B oracle: no
language model, so they're free to run and exactly repeatable.

E1, question selection: the Question Engine (value of information) against simpler policies
that ask the same questions, grouped the same way, in another order:
  every     - every question that applies, in dictionary order (the long-form baseline)
  fixed     - dictionary order, stopping by our stop rule
  random    - random order (seeded by the case), stopping by our stop rule
E2, silent defaults: after every question of the Question Engine's interview, what results
shown at that point would claim. "naive" reports the engine's answer as is, with every
unknown read as 0/no; "tracked" is what get_results reports (nothing until the essentials
are in; programs that an unasked or declined question could still change are "if ...").

Run from engine/ (its environment):  uv run python ../eval/experiments.py [e1] [e2] [--workers N]
Raw results go to eval/results/; the tables to docs/research-results.md (generated: don't edit).
"""

import argparse
import json
import os
import random
import statistics
import sys
from collections import defaultdict
from datetime import date
from multiprocessing import Pool
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))

import run as scorecard  # noqa: E402
import simulate  # noqa: E402
import tier_b  # noqa: E402
from unclaimed_engine.batch import PERSON_SEP  # noqa: E402
from unclaimed_engine.calculate import calculate  # noqa: E402
from unclaimed_engine.interview import (  # noqa: E402
    _candidate, _county_question, _question_view, _view_key, conditional_on_declined, next_question,
    open_questions)

RESULTS = ROOT / "eval" / "results"
OUT = ROOT / "docs" / "research-results.md"
POLICIES = ("engine", "every", "fixed", "random")


# ---- E1: question-selection policies ------------------------------------------------------

def _ask(h, pid, q, decision: dict) -> dict:
    """`decision` with its question replaced by (pid, q), grouped as the engine groups it."""
    keys = {(p, o.id) for p, o in open_questions(h)}
    c = _candidate(h, pid, q, keys)
    return {**decision, "ask": _question_view(pid, q), "together": [_question_view(*_view_key(t)) for t in c.together]}


def every_question(h) -> dict:
    if location := _county_question(h):
        return {"stop": False, "core": True, "ask": location, "together": []}
    open_ = open_questions(h)
    return _ask(h, *open_[0], {"stop": False}) if open_ else {"stop": True}


def reordered(pick):
    """Our stop rule and core questions, but `pick` chooses among the open questions."""
    def decide(h) -> dict:
        d = next_question(h)
        return d if d["stop"] or d["core"] else _ask(h, *pick(open_questions(h)), d)
    return decide


def policy(name: str, case_id: str):
    if name == "engine":
        return next_question
    if name == "every":
        return every_question
    if name == "fixed":
        return reordered(lambda open_: open_[0])
    rng = random.Random(case_id)  # the same order every run
    return reordered(lambda open_: rng.choice(open_))


def _e1_case(name: str, case: dict) -> dict:
    try:
        return {"policy": name, **simulate.run(case, decide=policy(name, case["id"]))}
    except Exception as e:  # a broken case is a finding, not a crash
        return {"policy": name, "id": case["id"], "error": f"{type(e).__name__}: {e}"}


# ---- E2: results shown mid-interview ------------------------------------------------------

def _e2_case(case: dict) -> dict:
    truth = simulate._truth(case)
    full = simulate.apply(simulate._start(case).model_copy(update={"county": case.get("county")}), truth)
    ids = [p["id"] for p in case["people"]]
    want = simulate._programs(calculate(full), ids)
    rows = []

    def observe(h, d):
        if _county_question(h):  # where the household lives isn't known yet: nothing to show
            return
        got = simulate._programs(calculate(h), ids)
        claimed = {p for p in want if got[p][0]}
        false = {p for p in claimed if not want[p][0]}
        # What get_results says: no results before the essentials; "if ..." for programs an
        # unasked (decision's `unanswered`) or declined question could still change.
        ready = d["stop"] or not d["core"]
        hedged = set(d.get("unanswered", {})) | set(conditional_on_declined(h))
        flat = {p for p in claimed if p.split(PERSON_SEP)[0] not in hedged} if ready else set()
        rows.append({"asked": len(rows), "naive_false": len(false), "tracked_false": len(flat & false),
                     "tracked_ready": ready, "true_claims": len(claimed - false),
                     "true_hedged": len((claimed - false) - flat) if ready else 0})

    try:
        simulate.run(case, on_turn=observe)
    except Exception as e:
        return {"id": case["id"], "error": f"{type(e).__name__}: {e}"}
    return {"id": case["id"], "turns": rows}


# ---- report -------------------------------------------------------------------------------

def _pct(n: int, d: int) -> str:
    return f"{n} ({100 * n / d:.1f}%)" if d else "0"


def e1_table(results: list[dict]) -> str:
    by = defaultdict(list)
    for r in results:
        by[r["policy"]].append(r)
    lines = ["## E1: question selection", "",
             "Same households, same oracle, same question groups; only the choice of the next question differs.", "",
             "| Policy | Households | False \"you qualify\" | Missed a program | Questions: median / p95 / max | Errors |",
             "|---|---|---|---|---|---|"]
    for name in POLICIES:
        rows = by.get(name, [])
        ok = [r for r in rows if "error" not in r]
        turns = sorted(r["turns"] for r in ok)
        spread = f"{statistics.median(turns):.0f} / {turns[int(0.95 * (len(turns) - 1))]} / {turns[-1]}" if turns else "-"
        lines.append(f"| {name} | {len(ok)} | {_pct(sum(1 for r in ok if r['false_qualify']), len(ok))} | "
                     f"{_pct(sum(1 for r in ok if r['missed']), len(ok))} | {spread} | {len(rows) - len(ok)} |")
    return "\n".join(lines) + "\n"


def e2_table(results: list[dict]) -> str:
    ok = [r for r in results if "error" not in r]
    at = defaultdict(list)
    for r in ok:
        for row in r["turns"]:
            at[row["asked"]].append(row)
    lines = ["## E2: results shown mid-interview", "",
             "If results were shown after this many questions of the Question Engine's interview: households where they "
             "would claim at least one program the full answer says they don't qualify for. *Naive* takes the engine's "
             "answer with unknowns read as 0/no; *tracked* is what `get_results` shows (no results before the essentials, "
             "\"if ...\" where an unasked or declined answer could change eligibility). *Hedged* is the share of true "
             "claims shown as \"if ...\" rather than \"you qualify\": the cost of being safe.", "",
             "| Questions asked | Households | Naive: false \"you qualify\" | Tracked: false \"you qualify\" | Tracked: no results yet | Hedged true claims |",
             "|---|---|---|---|---|---|"]
    for k in sorted(at):
        rows = at[k]
        true_claims = sum(r["true_claims"] for r in rows if r["tracked_ready"])
        lines.append(f"| {k} | {len(rows)} | {_pct(sum(1 for r in rows if r['naive_false']), len(rows))} | "
                     f"{_pct(sum(1 for r in rows if r['tracked_false']), len(rows))} | "
                     f"{_pct(sum(1 for r in rows if not r['tracked_ready']), len(rows))} | "
                     f"{_pct(sum(r['true_hedged'] for r in rows), true_claims)} |")
    if errors := [r for r in results if "error" in r]:
        lines += ["", f"Errors: {len(errors)}"]
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("experiments", nargs="*", default=["e1", "e2"])
    ap.add_argument("--workers", type=int, default=max(1, min(12, (os.cpu_count() or 2) // 2)))
    args = ap.parse_args()
    cases = yaml.safe_load((ROOT / "eval" / "tier_a.yaml").read_text(encoding="utf-8")) + tier_b.cases()
    RESULTS.mkdir(exist_ok=True)
    version = scorecard._version()
    sections = {}
    if OUT.exists():  # keep the experiment not re-run this time
        for part in OUT.read_text(encoding="utf-8").split("\n## ")[1:]:
            sections[part[:2].lower()] = "## " + part
    with Pool(args.workers) as pool:
        if "e1" in args.experiments:
            jobs = [(name, case) for name in POLICIES for case in cases]
            e1 = pool.starmap(_e1_case, jobs, chunksize=1)
            (RESULTS / "e1.json").write_text(json.dumps(e1, indent=1))
            sections["e1"] = e1_table(e1) + f"\nRun on {date.today()} from `{version}`.\n"
        if "e2" in args.experiments:
            e2 = pool.map(_e2_case, cases, chunksize=1)
            (RESULTS / "e2.json").write_text(json.dumps(e2, indent=1))
            sections["e2"] = e2_table(e2) + f"\nRun on {date.today()} from `{version}`.\n"
    OUT.write_text("# Research results\n\nGenerated by `eval/experiments.py` (don't edit by hand); the plan is "
                   "`docs/research-plan.md`. Tier A and Tier B households, oracle answers.\n\n"
                   + "\n".join(sections[k] for k in sorted(sections)), encoding="utf-8")
    print(f"-> {OUT}")


if __name__ == "__main__":
    main()
