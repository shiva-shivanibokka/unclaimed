"""Research experiment E3 (docs/research-plan.md): where should an interviewing agent's
decisions live? The same simulated people (a model playing each Tier A household, in
everyday words) talk with three designs of Alexa, all on the same model:

  split  - ours: the model only talks; the MCP server's tools choose each question, decide
           when to stop and compute the results (get_results is what the screen shows)
  tool   - the model gets the same calculator (the engine's /calculate) as a tool, but
           chooses the questions and when to stop itself, and reports the results
  alone  - the model alone, from its own knowledge of the rules

All three share Alexa's voice and speaking rules (simulator/simulator/voice.md) and the
program list. Every design ends on the results screen: `split` shows get_results; `tool`
and `alone` call show_results with the programs they tell the person they qualify for
("qualify") or might ("maybe": the "if ..." of our design). That screen is what's scored.
The person is always played by the other model family from Alexa's.

Run (simulator env, from simulator/), with the engine (and for `split` the MCP server) up:
  uv run python ../eval/e3.py --model MODEL_ID --designs split tool alone --budget 60 [--limit N]
Needs `uv run python ../eval/tier_c.py prepare` first. `--budget` is the total for all E3
runs so far (every model). Rows, with transcripts, go to paper/data/e3-*.json (published
with the paper); the table to docs/research-results.md. Resumable: finished conversations
are kept. Don't run alongside eval/experiments.py (both rewrite docs/research-results.md).
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
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))
sys.path.insert(0, str(ROOT / "simulator"))

import tier_c  # noqa: E402
from strands import Agent, tool  # noqa: E402
from strands.models import BedrockModel  # noqa: E402

from simulator import agent as alexa  # noqa: E402

ENGINE_URL = os.environ.get("ENGINE_URL", "http://localhost:8000")
DATA = ROOT / "paper" / "data"
OUT = ROOT / "docs" / "research-results.md"
DESIGNS = ("split", "tool", "alone")
# The two model families compared. USD per million tokens: input, output, cache read, cache
# write (Bedrock on-demand, us-east-1, read Oct 1 2026 from aws.amazon.com/bedrock/pricing).
# Used only to stop at the budget; the AWS bill is the truth.
PRICES = {
    "us.anthropic.claude-haiku-4-5-20251001-v1:0": (1.00, 5.00, 0.10, 1.25),
    "us.amazon.nova-2-lite-v1:0": (0.30, 2.50, 0.075, 0.30),
}
FIRST_RESERVE = 1.00  # USD held back per conversation in flight until one has been costed


def person_model(model: str) -> str:
    """The person is played by the other family, so Alexa never talks to itself."""
    return next(m for m in PRICES if m != model)


def _get(path: str):
    return json.loads(urlopen(ENGINE_URL + path, timeout=60).read())


def _post(path: str, body: dict):
    req = Request(ENGINE_URL + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    try:
        return json.loads(urlopen(req, timeout=120).read())
    except HTTPError as e:  # the engine says what's wrong (as our MCP server passes on to `split`)
        return {"error": json.loads(e.read() or b"{}").get("detail", str(e))}


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
        inputSchema={"json": {"type": "object", "required": ["household"],
                              "properties": {"household": {"$ref": "#/$defs/Household"}}, "$defs": schema["$defs"]}})
    def calculate(household: dict) -> dict:
        r = _post("/calculate", household)
        if "error" in r:
            return r
        return {"programs": [{k: p[k] for k in ("id", "name", "eligible", "amount", "per") if k in p}
                             for p in r["programs"]],
                "depends_on_declined": r.get("conditional", {})}
    return calculate


def _prompt(design: str, programs: list[dict]) -> str:
    listed = "\n".join(f"- {p['id']}: {p['name']}" for p in programs)
    how = ("Use the `calculate` tool for every eligibility and amount: never decide them yourself."
           if design == "tool" else
           "You have no calculator: decide from what you know of each program's current rules.")
    return (f"{alexa.VOICE}\nHow to run the screening:\n"
            f"Find out which of these programs the household may qualify for:\n{listed}\n"
            "Ask for their ZIP code and who lives with them, then whatever else you need, one question at a time. "
            f"{how} When you know enough, call `show_results`, then tell them the results in a sentence or two.\n")


# ---- one conversation ---------------------------------------------------------------------

def cost(model: str, tokens: dict) -> float:
    """Bedrock's inputTokens are the new input only; cache reads and writes are counted apart."""
    i, o, cr, cw = PRICES[model]
    return (tokens.get("input", 0) * i + tokens.get("output", 0) * o + tokens.get("cache_read", 0) * cr
            + tokens.get("cache_write", 0) * cw) / 1e6


def converse(case: dict, design: str, model: str, usage: dict) -> dict:
    """One conversation. `usage` collects tokens as they're spent, so a conversation that
    fails partway is still costed."""
    usage.update(alexa={}, person={})
    person = Agent(model=BedrockModel(model_id=person_model(model), region_name=alexa.REGION),
                   system_prompt=tier_c._person_prompt(case), callback_handler=None)
    screen: dict = {}
    if design == "split":
        kwargs = {"model_id": model}
    else:
        programs = _programs(_state(case))
        tools = [_show_results_tool(programs, screen)]
        if design == "tool":
            tools.append(_calculate_tool(_household_schema()))
        kwargs = {"model_id": model, "tools": tools, "system_prompt": _prompt(design, programs)}
    history: list[dict] = []
    said = "Alexa, open Unclaimed."
    turns, transcript, calls = 0, [], {}
    while turns < tier_c.MAX_TURNS:
        turns += 1
        out = alexa.turn(history, said, **kwargs)
        history = out["messages"]
        calls.update(_tool_calls(history))  # the agent drops old messages: collect calls every turn
        for k, v in out["tokens"].items():
            usage["alexa"][k] = usage["alexa"].get(k, 0) + v
        transcript += [("person", said), ("alexa", out["reply"])]
        reply = person(out["reply"])
        u = reply.metrics.accumulated_usage  # the person's agent keeps its history: running totals
        usage["person"] = {"input": u["inputTokens"], "output": u["outputTokens"],
                           "cache_read": u.get("cacheReadInputTokens", 0), "cache_write": u.get("cacheWriteInputTokens", 0)}
        reply = str(reply).strip()
        if tier_c.DONE.search(reply):
            transcript.append(("person", reply))
            break
        said = reply
    if design == "split":
        results = tier_c._results(history)
        if results and results.get("programs"):
            # "if ..." on our screen: an unasked or declined answer (whether or not eligible
            # without it), or a condition the calculator can't check.
            ps = results["programs"]
            screen = {"qualify": [p["id"] for p in ps if p["eligible"] and not (p.get("conditional_on") or p.get("if_also"))],
                      "maybe": [p["id"] for p in ps if p.get("conditional_on") or (p["eligible"] and p.get("if_also"))]}
    truth = case["truth"]
    qualify, maybe = set(screen.get("qualify", [])), set(screen.get("maybe", []))
    eligible = {p for p in truth if truth[p]["eligible"]}
    return {
        "id": case["id"], "design": design, "model": model, "person_model": person_model(model),
        "finished": bool(screen), "turns": turns,
        "false_qualify": sorted(qualify - eligible), "false_maybe": sorted(maybe - eligible),
        "missed": sorted(eligible - qualify - maybe), "hedged": sorted(eligible & maybe),
        "eligible": sorted(eligible), "transcript": transcript, "tool_calls": list(calls.values()),
    }


def _tool_calls(history: list[dict]) -> dict[str, dict]:
    """Tool calls in the history by id, with their input and whether they failed (for failure analysis)."""
    failed = {b["toolResult"]["toolUseId"] for m in history for b in m["content"]
              if "toolResult" in b and b["toolResult"].get("status") == "error"}
    return {b["toolUse"]["toolUseId"]: {"name": b["toolUse"]["name"], "input": b["toolUse"]["input"],
                                        "failed": b["toolUse"]["toolUseId"] in failed}
            for m in history for b in m["content"] if "toolUse" in b}


# ---- report -------------------------------------------------------------------------------

def table(rows: list[dict]) -> str:
    lines = ["## E3: where decisions live", "",
             "Simulated conversations: a model plays each Tier A household in everyday words, always from the other "
             "model family than Alexa's. Same people and same Alexa model within a block; only the design differs. "
             "Scored on the results screen, over every conversation that ran (a conversation that never reached "
             "results told the person nothing: it counts as missing every program they qualify for). A false \"you "
             "qualify\" is a program shown as \"qualify\" that the full-information answer says they don't qualify for.", "",
             "| Model | Design | Conversations | Reached results | False \"you qualify\" | Missed a program | "
             "Eligible programs shown as \"maybe\" | Turns: median | Cost | Errors |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for model in sorted({r["model"] for r in rows}):
        for design in DESIGNS:
            rs = [r for r in rows if r["model"] == model and r["design"] == design]
            if not rs:
                continue
            ok = [r for r in rs if "error" not in r]
            n = len(ok)

            def pct(k):
                return f"{k} ({100 * k / n:.0f}%)" if n else "-"
            missed = sum(1 for r in ok if r["missed"] or (not r["finished"] and r["eligible"]))
            hedged = sum(len(r["hedged"]) for r in ok)
            eligible = sum(len(r["eligible"]) for r in ok)
            lines.append(
                f"| `{model.split('.')[-1]}` | {design} | {n} | {pct(sum(1 for r in ok if r['finished']))} | "
                f"{pct(sum(1 for r in ok if r['false_qualify']))} | {pct(missed)} | {hedged} of {eligible} | "
                f"{statistics.median(r['turns'] for r in ok) if ok else '-'} | ${sum(r['cost'] for r in rs):.2f} | "
                f"{len(rs) - n} |")
    return "\n".join(lines) + f"\n\nRun on {date.today()}.\n"


def _write(path: Path, text: str) -> None:
    """Replace a file in one step, so a crash mid-write can't lose paid results."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=alexa.MODEL_ID, choices=sorted(PRICES))
    ap.add_argument("--designs", nargs="+", default=list(DESIGNS), choices=DESIGNS)
    ap.add_argument("--budget", type=float, required=True, help="USD for all E3 runs so far: stop starting past this")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()
    cases = json.loads(tier_c.CASES.read_text())[:args.limit]
    DATA.mkdir(parents=True, exist_ok=True)
    raw = DATA / f"e3-{args.model.split('.')[-1].replace(':', '-')}.json"  # no ':' in Windows file names
    rows = json.loads(raw.read_text()) if raw.exists() else []
    done = {(r["id"], r["design"]) for r in rows if "error" not in r}
    jobs = [(c, d) for d in args.designs for c in cases if (c["id"], d) not in done]  # resumable
    lock = threading.Lock()
    state = {"spent": sum(r["cost"] for f in DATA.glob("e3-*.json") for r in json.loads(f.read_text())),
             "running": 0, "worst": 0.0}

    def one(job):
        case, design = job
        with lock:  # start only if the conversations in flight can't push past the budget
            if state["spent"] + (state["running"] + 1) * (state["worst"] or FIRST_RESERVE) > args.budget:
                return None
            state["running"] += 1
        usage: dict = {}
        try:
            row = converse(case, design, args.model, usage)
        except Exception as e:  # a failed conversation is a finding, not a crash
            row = {"id": case["id"], "design": design, "model": args.model, "error": f"{type(e).__name__}: {e}"}
        row["cost"] = round(cost(args.model, usage.get("alexa", {})) + cost(person_model(args.model), usage.get("person", {})), 4)
        with lock:
            state["spent"] += row["cost"]
            state["running"] -= 1
            state["worst"] = max(state["worst"], row["cost"])
            rows[:] = [r for r in rows if (r["id"], r["design"]) != (case["id"], design)] + [row]
            _write(raw, json.dumps(rows, indent=1))
        print(f"{design:5} {case['id']:28} ${row['cost']:.3f}  total ${state['spent']:.2f}  "
              f"{row.get('error') or ('FALSE QUALIFY ' + ','.join(row['false_qualify']) if row['false_qualify'] else 'ok')}",
              flush=True)
        return row

    t = time.perf_counter()
    with ThreadPoolExecutor(args.workers) as pool:
        ran = [r for r in pool.map(one, jobs) if r]
    print(f"{len(ran)} of {len(jobs)} conversations in {time.perf_counter() - t:.0f} s; E3 total ${state['spent']:.2f}")
    everything = [r for f in sorted(DATA.glob("e3-*.json")) for r in json.loads(f.read_text())]
    text = OUT.read_text(encoding="utf-8") if OUT.exists() else "# Research results\n"
    _write(OUT, text.split("## E3:")[0].rstrip() + "\n\n" + table(everything))
    print(f"-> {OUT}")


if __name__ == "__main__":
    main()
