"""Research experiment E3 (docs/research-plan.md): where should an interviewing agent's
decisions live? The same simulated people (Tier C: a model playing each Tier A household,
in everyday words) talk with three designs of Alexa, all on the same model:

  split  - ours: the model only talks; the MCP server's tools choose each question, decide
           when to stop and compute the results (get_results is what the screen shows)
  tool   - the model gets the same calculator (the engine's /calculate) as a tool, but
           chooses the questions and when to stop itself, and reports the results
  alone  - the model alone, from its own knowledge of the rules

Every design ends on the results screen: `split` shows get_results; `tool` and `alone`
call show_results with the programs they tell the person they qualify for ("qualify") or
might ("maybe": the "if ..." of our design). That screen is what's scored.

Run (simulator env, from simulator/), with the engine (and for `split` the MCP server) up:
  uv run python ../eval/e3.py --model MODEL_ID --designs split tool alone --budget 15 [--limit N]
Needs `uv run python ../eval/tier_c.py prepare` first. Raw rows go to eval/results/e3-*.json;
the table to docs/research-results.md.
"""

import argparse
import json
import os
import statistics
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))
sys.path.insert(0, str(ROOT / "simulator"))

import tier_c  # noqa: E402
from strands import Agent, tool  # noqa: E402
from strands.models import BedrockModel  # noqa: E402

from simulator import agent as alexa  # noqa: E402

ENGINE_URL = os.environ.get("ENGINE_URL", "http://localhost:8000")
RESULTS = ROOT / "eval" / "results"
OUT = ROOT / "docs" / "research-results.md"
DESIGNS = ("split", "tool", "alone")
# The simulated person is always this model (cheap; a different family from Claude).
PERSON_MODEL = "us.amazon.nova-2-lite-v1:0"
# USD per million tokens: input, output, cache read, cache write (Bedrock on-demand, us-east-1,
# Oct 2026: aws.amazon.com/bedrock/pricing). Used only to stop at the budget; the bill is
# the truth.
PRICES = {
    "us.anthropic.claude-haiku-4-5-20251001-v1:0": (1.00, 5.00, 0.10, 1.25),
    "us.amazon.nova-2-lite-v1:0": (0.30, 2.50, 0.075, 0.30),
}
# The speaking rules all designs share: the part of Alexa's prompt before how to run *our*
# screening.
SPEAKING = alexa.SYSTEM_PROMPT.split("How to run the screening:")[0]


def _get(path: str):
    return json.loads(urlopen(ENGINE_URL + path, timeout=60).read())


def _post(path: str, body: dict):
    req = Request(ENGINE_URL + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    return json.loads(urlopen(req, timeout=120).read())


def _household_schema() -> dict:
    """The engine's own household schema (its OpenAPI components, as $defs)."""
    schemas = _get("/openapi.json")["components"]["schemas"]
    return {"$defs": json.loads(json.dumps(schemas).replace("#/components/schemas/", "#/$defs/"))}


def _programs(state: str) -> list[dict]:
    return [{"id": p["id"], "name": p["state_names"].get(state, p["name"])}
            for p in _get("/programs") if state in p["states"]]


def _state(case: dict) -> str:
    return next(iter(_get(f"/zip/{case['zip']}")["states"]))  # Tier A ZIPs are in one state


# ---- the baselines' tools -----------------------------------------------------------------

def _show_results_tool(programs: list[dict], screen: dict):
    ids = [p["id"] for p in programs]

    @tool(name="show_results", description=(
        "Show the results on the screen before telling the person. `qualify`: programs you tell them they "
        "qualify for. `maybe`: programs they might qualify for, depending on something you don't know. "
        "Leave out the rest."),
        inputSchema={"json": {"type": "object", "required": ["qualify", "maybe"], "properties": {
            "qualify": {"type": "array", "items": {"type": "string", "enum": ids}},
            "maybe": {"type": "array", "items": {"type": "string", "enum": ids}}}}})
    def show_results(qualify: list[str], maybe: list[str]) -> str:
        screen.update(qualify=list(qualify), maybe=list(maybe))
        return "Shown. Now tell them in a sentence or two."
    return show_results


def _calculate_tool(schema: dict):
    @tool(name="calculate", description=(
        "The exact benefits calculator (PolicyEngine-US). Pass everything you know about the household; "
        "anything you leave out is read as zero, no, or the default. Income and expenses are yearly amounts."),
        inputSchema={"json": {"type": "object", "required": ["household"], "properties": {"household": {"$ref": "#/$defs/Household"}},
                              "$defs": schema["$defs"]}})
    def calculate(household: dict) -> dict:
        r = _post("/calculate", household)
        return {"programs": [{k: p[k] for k in ("id", "name", "eligible", "amount", "per") if k in p}
                             for p in r["programs"]],
                "depends_on_declined": r.get("conditional", {})}
    return calculate


def _prompt(design: str, programs: list[dict]) -> str:
    listed = "\n".join(f"- {p['id']}: {p['name']}" for p in programs)
    how = ("Use the `calculate` tool for every eligibility and amount: never decide them yourself."
           if design == "tool" else
           "You have no calculator: decide from what you know of each program's current rules.")
    return (f"{SPEAKING}How to run the screening:\n"
            f"Find out which of these programs the household may qualify for:\n{listed}\n"
            "Ask for their ZIP code and who lives with them, then whatever else you need, one question at a time. "
            f"{how} When you know enough, call `show_results`, then tell them the results in a sentence or two.\n")


# ---- one conversation ---------------------------------------------------------------------

def _cost(model: str, tokens: dict) -> float:
    i, o, cr, cw = PRICES[model]
    fresh = tokens["input"] - tokens["cache_read"] - tokens.get("cache_write", 0)
    return (max(fresh, 0) * i + tokens["output"] * o + tokens["cache_read"] * cr
            + tokens.get("cache_write", 0) * cw) / 1e6


def converse(case: dict, design: str, model: str) -> dict:
    person = Agent(model=BedrockModel(model_id=PERSON_MODEL, region_name=alexa.REGION),
                   system_prompt=tier_c._person_prompt(case), callback_handler=None)
    screen: dict = {}
    if design == "split":
        kwargs = {"model_id": model}
    else:
        state = _state(case)
        programs = _programs(state)
        tools = [_show_results_tool(programs, screen)]
        if design == "tool":
            tools.append(_calculate_tool(_household_schema()))
        kwargs = {"model_id": model, "tools": tools, "system_prompt": _prompt(design, programs)}
    history: list[dict] = []
    said = "Alexa, open Unclaimed."
    turns, alexa_tokens, person_tokens, transcript = 0, {}, {"input": 0, "output": 0, "cache_read": 0}, []
    while turns < tier_c.MAX_TURNS:
        turns += 1
        out = alexa.turn(history, said, **kwargs)
        history = out["messages"]
        for k, v in out["tokens"].items():
            alexa_tokens[k] = alexa_tokens.get(k, 0) + v
        transcript += [("person", said), ("alexa", out["reply"])]
        reply = person(out["reply"])
        usage = reply.metrics.accumulated_usage
        person_tokens = {"input": usage["inputTokens"], "output": usage["outputTokens"],
                         "cache_read": usage.get("cacheReadInputTokens", 0)}
        reply = str(reply).strip()
        if "DONE" in reply:
            transcript.append(("person", reply))
            break
        said = reply
    if design == "split":
        results = tier_c._results(history)
        if results and results.get("programs"):
            screen = {"qualify": [p["id"] for p in results["programs"] if p["eligible"] and not p.get("conditional_on")],
                      "maybe": [p["id"] for p in results["programs"] if p["eligible"] and p.get("conditional_on")]}
    truth = case["truth"]
    qualify, maybe = set(screen.get("qualify", [])), set(screen.get("maybe", []))
    eligible = {p for p in truth if truth[p]["eligible"]}
    return {
        "id": case["id"], "design": design, "model": model, "finished": bool(screen), "turns": turns,
        "false_qualify": sorted(qualify - eligible), "false_maybe": sorted(maybe - eligible),
        "missed": sorted(eligible - qualify - maybe), "hedged": sorted(eligible & maybe),
        "eligible": sorted(eligible),
        "cost": round(_cost(model, alexa_tokens) + _cost(PERSON_MODEL, person_tokens), 4),
        "tokens": alexa_tokens, "transcript": transcript,
    }


# ---- report -------------------------------------------------------------------------------

def table(rows: list[dict]) -> str:
    lines = ["## E3: where decisions live", "",
             "Simulated conversations (a model plays each Tier A household in everyday words; the person is always "
             f"`{PERSON_MODEL}`). Same people, same model for Alexa within a block; only the design differs. Scored on "
             "the results screen: a program shown as \"qualify\" that the full-information answer says they don't "
             "qualify for is a false \"you qualify\".", "",
             "| Model | Design | Conversations | Reached results | False \"you qualify\" | Missed a program | "
             "Eligible programs shown as \"maybe\" | Turns: median | Cost |",
             "|---|---|---|---|---|---|---|---|---|"]
    for model in sorted({r["model"] for r in rows}):
        for design in DESIGNS:
            rs = [r for r in rows if r["model"] == model and r["design"] == design]
            if not rs:
                continue
            ok = [r for r in rs if "error" not in r]
            done = [r for r in ok if r["finished"]]
            n = len(done)
            hedged = sum(len(r["hedged"]) for r in done)
            eligible = sum(len(r["eligible"]) for r in done)

            def pct(k):
                return f"{k} ({100 * k / n:.0f}%)" if n else "-"
            lines.append(
                f"| `{model.split('.')[-1]}` | {design} | {len(rs)} | {n} | {pct(sum(1 for r in done if r['false_qualify']))} | "
                f"{pct(sum(1 for r in done if r['missed']))} | {hedged} of {eligible} | "
                f"{statistics.median(r['turns'] for r in ok) if ok else '-'} | ${sum(r.get('cost', 0) for r in ok):.2f} |")
    return "\n".join(lines) + f"\n\nRun on {date.today()}.\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True, choices=sorted(PRICES))
    ap.add_argument("--designs", nargs="+", default=list(DESIGNS), choices=DESIGNS)
    ap.add_argument("--budget", type=float, required=True, help="USD: stop starting conversations past this")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()
    cases = json.loads(tier_c.CASES.read_text())[:args.limit]
    raw = RESULTS / f"e3-{args.model.split('.')[-1]}.json"
    rows = json.loads(raw.read_text()) if raw.exists() else []
    done = {(r["id"], r["design"]) for r in rows if "error" not in r}
    jobs = [(c, d) for d in args.designs for c in cases if (c["id"], d) not in done]  # resumable
    spent, lock = 0.0, threading.Lock()

    def one(job):
        nonlocal spent
        case, design = job
        with lock:
            if spent >= args.budget:
                return None
        try:
            row = converse(case, design, args.model)
        except Exception as e:  # a failed conversation is a finding, not a crash
            row = {"id": case["id"], "design": design, "model": args.model, "error": f"{type(e).__name__}: {e}"}
        with lock:
            spent += row.get("cost", 0)
            rows[:] = [r for r in rows if (r["id"], r["design"]) != (case["id"], design)] + [row]
            raw.write_text(json.dumps(rows, indent=1))
        print(f"{design:5} {case['id']:24} ${row.get('cost', 0):.3f}  total ${spent:.2f}  "
              f"{row.get('error') or ('FALSE QUALIFY ' + ','.join(row['false_qualify']) if row['false_qualify'] else 'ok')}",
              flush=True)
        return row

    t = time.perf_counter()
    RESULTS.mkdir(exist_ok=True)
    with ThreadPoolExecutor(args.workers) as pool:
        list(pool.map(one, jobs))
    print(f"{len(jobs)} conversations in {time.perf_counter() - t:.0f} s, ${spent:.2f} this run")
    everything = [r for f in sorted(RESULTS.glob("e3-*.json")) for r in json.loads(f.read_text())]
    text = OUT.read_text(encoding="utf-8") if OUT.exists() else "# Research results\n"
    head = text.split("## E3:")[0].rstrip() + "\n\n"
    OUT.write_text(head + table(everything), encoding="utf-8")
    print(f"-> {OUT}")


if __name__ == "__main__":
    main()
