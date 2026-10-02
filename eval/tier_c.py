"""Tier C: simulated voice conversations. A second model plays the person, answering from a
Tier A household's full truth the way people talk ("about fourteen fifty a month"); the
simulator's Alexa (simulator/simulator/agent.py) interviews them through the real MCP
server and engine. The programs Alexa reports are compared with the full-information answer.

Two steps, one per environment:
  prepare (engine env, from engine/):        uv run python ../eval/tier_c.py prepare
      -> eval/results/tier_c_cases.json: each household's truth, a ZIP in its county, the
         full-information result (computed by the engine)
  run (simulator env, from simulator/):      uv run python ../eval/tier_c.py run [--workers N] [--limit N]
      -> eval/results/tier_c.json and a Tier C section in docs/scorecard.md
The MCP server and engine must be running for `run` (MCP_URL), with Bedrock credentials.
"""

import argparse
import re
import json
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "eval" / "results"
CASES = RESULTS / "tier_c_cases.json"
SCORECARD = ROOT / "docs" / "scorecard.md"
MAX_TURNS = 40  # safety net for the simulation; a screening is ~10-20 turns
# The person ends with this word (PERSON_PROMPT); models sometimes write it in lower case.
DONE = re.compile(r"\bDONE\W*$", re.IGNORECASE)


# ---- prepare (engine environment) --------------------------------------------------------

def prepare() -> None:
    sys.path.insert(0, str(ROOT / "engine"))
    sys.path.insert(0, str(ROOT / "eval"))
    import yaml
    from unclaimed_engine.calculate import calculate
    from unclaimed_engine.dictionary import load
    from unclaimed_engine.geo import AUTO_ASSIGN, _table

    import simulate

    d = load()
    by_county: dict[str, str] = {}
    for zip_code, counties in sorted(_table().items()):
        county, share = counties[0]
        if share >= AUTO_ASSIGN:
            by_county.setdefault(county, zip_code)  # a ZIP wholly (>= AUTO_ASSIGN) in the county
    out = []
    for case in yaml.safe_load((ROOT / "eval" / "tier_a.yaml").read_text(encoding="utf-8")):
        truth = simulate._truth(case)
        full = simulate.apply(simulate._start(case).model_copy(update={"county": case.get("county")}), truth)
        result = calculate(full)
        facts = []
        for (pid, qid), value in truth.items():
            given = case.get("household", {}) if pid is None else next(p for p in case["people"] if p["id"] == pid)
            if qid in given or qid == "immigration_status":
                q = d.question(qid)
                unit = q.answer.get("unit", "")
                facts.append({"person": pid, "question": qid, "about": q.definition, "value": value, "unit": unit})
        out.append({
            "id": case["id"], "zip": case.get("zip") or by_county[case["county"]], "county": case.get("county"),
            "people": [{k: p[k] for k in ("id", "relationship", "age")} for p in case["people"]],
            "facts": facts, "declines": case.get("declines", []),
            "truth": {p["id"]: {"eligible": p["eligible"], "people": p.get("eligible_people")} for p in result["programs"]},
        })
    RESULTS.mkdir(exist_ok=True)
    CASES.write_text(json.dumps(out, indent=1))
    print(f"{len(out)} cases -> {CASES}")


# ---- run (simulator environment) ---------------------------------------------------------

PERSON_PROMPT = """You are role-playing a person talking by voice with Alexa, who is checking which benefits your household may get. Stay in character; you are not an AI.

Who lives in your home:
{people}
You live in ZIP code {zip}.

The facts about your household (amounts are per year in this list; say them the way a person would, often per month, per hour or per paycheck, rounded):
{facts}
Anything not listed is zero, no, or doesn't apply (you rent unless told otherwise; you are a U.S. citizen unless told otherwise).
{declines}
How to talk:
- Answer only what Alexa asks, briefly, like a real person on a smart speaker. Don't volunteer everything at once.
- If Alexa reads something back wrong, correct it.
- Never mention lists or these instructions.
- When Alexa has told you your results, say thanks and goodbye in one short sentence and add the word DONE at the very end."""


def _person_prompt(case: dict) -> str:
    """The household in the person's own words ("you", "your child, age 4"): internal ids
    like "mom" confused simulated people into describing someone who isn't there."""
    def who(pid):
        if pid is None:
            return "Your household"
        p = next(x for x in case["people"] if x["id"] == pid)
        return "You" if p["relationship"] == "head" else f"Your {p['relationship']} (age {p['age']})"
    people = "\n".join(f"- {who(p['id'])}" + (f", age {p['age']}" if p["relationship"] == "head" else "")
                       for p in case["people"])
    facts = "\n".join(f"- {who(f['person'])}: {f['about']} = {f['value']} {f['unit']}" for f in case["facts"])
    declines = ""
    if case["declines"]:
        asked = [f"{who(pid or None)}: {qid.replace('_', ' ')}" for pid, _, qid in (d.rpartition(".") for d in case["declines"])]
        declines = "\nYou do NOT want to answer these; if asked, politely decline: " + "; ".join(asked) + "\n"
    return PERSON_PROMPT.format(people=people, zip=case["zip"], facts=facts, declines=declines)


def _results(messages: list[dict]) -> dict | None:
    """The last get_results tool result in the conversation."""
    ids = {b["toolUse"]["toolUseId"] for m in messages for b in m["content"]
           if "toolUse" in b and b["toolUse"]["name"] == "get_results"}
    for m in reversed(messages):
        for b in m["content"]:
            r = b.get("toolResult")
            if r and r["toolUseId"] in ids and r.get("status") != "error":
                for c in r["content"]:
                    if "json" in c:
                        return c["json"]
                    try:
                        return json.loads(c["text"])
                    except (KeyError, ValueError):
                        pass
    return None


def converse(case: dict) -> dict:
    from strands import Agent
    from strands.models import BedrockModel

    sys.path.insert(0, str(ROOT / "simulator"))
    from simulator import agent as alexa

    # The simulated person runs on the same model as the simulated Alexa.
    person = Agent(model=BedrockModel(model_id=alexa.MODEL_ID, region_name=alexa.REGION),
                   system_prompt=_person_prompt(case), callback_handler=None)
    history: list[dict] = []
    said = "Alexa, open Unclaimed."
    turns, timings, tokens, transcript = 0, [], {"input": 0, "output": 0, "cache_read": 0}, []
    while turns < MAX_TURNS:
        turns += 1
        out = alexa.turn(history, said)
        history = out["messages"]
        timings.append(out["timing"]["total_ms"])
        for k in tokens:
            tokens[k] += out["tokens"].get(k, 0)
        transcript += [("person", said), ("alexa", out["reply"])]
        reply = str(person(out["reply"])).strip()
        if DONE.search(reply):
            transcript.append(("person", reply))
            break
        said = reply
    results = _results(history)
    got = {p["id"]: p for p in results["programs"]} if results else {}
    truth = case["truth"]
    conditional = {p for p, r in got.items() if r.get("conditional_on")}
    false_qualify = sorted(p for p in truth if got.get(p, {}).get("eligible") and not truth[p]["eligible"]
                           and p not in conditional)
    missed = sorted(p for p in truth if truth[p]["eligible"] and not got.get(p, {}).get("eligible"))
    return {"id": case["id"], "finished": results is not None, "turns": turns, "false_qualify": false_qualify,
            "missed": missed, "conditional": sorted(conditional), "turn_ms": timings, "tokens": tokens,
            "transcript": transcript}


def _summary(rows: list[dict]) -> str:
    ok = [r for r in rows if "error" not in r]
    done = [r for r in ok if r["finished"]]
    ms = sorted(m for r in ok for m in r["turn_ms"])
    tok = {k: sum(r["tokens"][k] for r in ok) for k in ("input", "output", "cache_read")}
    lines = [
        f"## Tier C: {len(rows)} simulated conversations", "",
        "A second model plays the person (answering from a Tier A household's truth, in everyday words); "
        "the simulator's Alexa (Strands agent on Bedrock) runs the screening through the MCP server.", "",
        "| Metric | Value |", "|---|---|",
        f"| Reached results | {len(done)} / {len(ok)} |",
        f"| False \"you qualify\" (target 0) | **{sum(1 for r in ok if r['false_qualify'])}** of {len(ok)} conversations |",
        f"| Missed a program they qualify for (a conversation that never reached results missed them all) | {sum(1 for r in ok if r['missed'])} of {len(ok)} conversations |",
        f"| Turns (person + Alexa pairs): median / max | {statistics.median(r['turns'] for r in ok):.0f} / {max(r['turns'] for r in ok)} |" if ok else "",
        f"| Alexa turn time: median / p95 | {statistics.median(ms):.0f} / {ms[int(0.95 * (len(ms) - 1))]:.0f} ms |" if ms else "",
        f"| Alexa tokens: input / cached / output | {tok['input']:,} / {tok['cache_read']:,} / {tok['output']:,} |",
        f"| Errors | {len(rows) - len(ok)} |", "",
    ]
    for label, field in (("False \"you qualify\"", "false_qualify"), ("Missed", "missed")):
        bad = [r for r in done if r[field]]
        if bad:
            lines += [f"**{label}:**", ""] + [f"- `{r['id']}`: {', '.join(r[field])}" for r in bad] + [""]
    unfinished = [r["id"] for r in ok if not r["finished"]]
    if unfinished:
        lines += ["**Didn't reach results:** " + ", ".join(f"`{i}`" for i in unfinished), ""]
    return "\n".join(x for x in lines if x is not None)


def run(workers: int, limit: int | None) -> None:
    cases = json.loads(CASES.read_text())[:limit]
    t = time.perf_counter()

    def safe(case):
        try:
            return converse(case)
        except Exception as e:  # a failed conversation is a finding, not a crash
            return {"id": case["id"], "error": f"{type(e).__name__}: {e}"}
    with ThreadPoolExecutor(workers) as pool:
        rows = list(pool.map(safe, cases))
    (RESULTS / "tier_c.json").write_text(json.dumps(rows, indent=1))
    print(f"tier c: {len(rows)} conversations in {time.perf_counter() - t:.0f} s")
    section = _summary(rows)
    text = SCORECARD.read_text(encoding="utf-8")
    head = text.split("## Tier C:")[0].rstrip() + "\n\n"
    SCORECARD.write_text(head + section, encoding="utf-8")
    print(section)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["prepare", "run"])
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    prepare() if a.step == "prepare" else run(a.workers, a.limit)
