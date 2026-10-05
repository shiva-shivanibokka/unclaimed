"""Run the eval tiers and write the scorecard (docs/scorecard.md, generated: don't edit).

Run from engine/ (its environment):  uv run python ../eval/run.py [a] [b] [--workers N]
Raw per-household results go to eval/results/ (not committed).
"""

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from datetime import date
from multiprocessing import Pool
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))

import simulate  # noqa: E402
import tier_b  # noqa: E402

RESULTS = ROOT / "eval" / "results"
SCORECARD = ROOT / "docs" / "scorecard.md"


def _run_case(case):
    try:
        return simulate.run(case)
    except Exception as e:  # a broken case is a finding, not a crash
        return {"id": case["id"], "error": f"{type(e).__name__}: {e}"}


def run_tier(name: str, cases: list[dict], workers: int) -> list[dict]:
    t = time.perf_counter()
    with Pool(workers) as pool:
        results = pool.map(_run_case, cases, chunksize=1)
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / f"tier_{name}.json").write_text(json.dumps(results, indent=1))
    print(f"tier {name}: {len(results)} households in {time.perf_counter() - t:.0f} s")
    return results


def _spread(xs: list[float]) -> str:
    xs = sorted(xs)
    return f"{statistics.median(xs):,.0f} / {xs[int(0.95 * (len(xs) - 1))]:,.0f} / {xs[-1]:,.0f}"


def summarize(name: str, results: list[dict]) -> str:
    ok = [r for r in results if "error" not in r]
    errors = [r for r in results if "error" in r]
    fq = [r for r in ok if r["false_qualify"]]
    missed = [r for r in ok if r["missed"]]
    exact = [r for r in ok if not r["false_qualify"] and not r["missed"]]
    turns = [r["turns"] for r in ok]
    ms = [m for r in ok for m in r["decision_ms"]]
    quick = [r["quick"] for r in ok]
    lines = [
        f"## Tier {name.upper()}: {len(results)} households",
        "",
        "First results (core questions, then a few more; the rest shown as \"maybe\"):",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| False \"you qualify\" | **{sum(1 for q in quick if q['false_qualify'])}** households |",
        f"| Missed a program they qualify for (not even a \"maybe\") | {sum(1 for q in quick if q['missed'])} households |",
        f"| Questions asked (turns): median / max | {statistics.median(q['turns'] for q in quick):.0f} / {max(q['turns'] for q in quick)} |" if quick else "",
        f"| Programs shown as \"maybe\": median / max | {statistics.median(len(q['maybe']) for q in quick):.0f} / {max(len(q['maybe']) for q in quick)} |" if quick else "",
        "",
        "After checking every \"maybe\" (as if the person asked about each):",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| False \"you qualify\" (target 0) | **{len(fq)}** households |",
        f"| Missed a program they qualify for | {len(missed)} households |",
        f"| Same eligibility as the full-information answer, every program | {len(exact)} / {len(ok)} |",
        f"| Questions asked (turns): median / max | {statistics.median(turns):.0f} / {max(turns)} |" if turns else "",
        f"| Amount error where both say eligible, per household: median / p95 / max | {_spread([r['amount_error'] for r in ok])} $/mo |" if ok else "",
        f"| Decision time: median / p95 | {statistics.median(ms):.0f} / {sorted(ms)[int(0.95 * (len(ms) - 1))]:.0f} ms |" if ms else "",
        f"| Results disclosed as conditional on a declined answer | {sum(1 for r in ok if r['conditional'])} households |",
        f"| Errors | {len(errors)} |",
        "",
    ]
    for label, rows, field in (("False \"you qualify\" in the first results", [r for r in ok if r["quick"]["false_qualify"]], "quick"),
                               ("False \"you qualify\"", fq, "false_qualify"), ("Missed", missed, "missed")):
        if rows and field == "quick":
            lines += [f"**{label}:**", ""] + [f"- `{r['id']}`: {', '.join(r['quick']['false_qualify'])}" for r in rows[:25]] + [""]
        elif rows:
            lines += [f"**{label}:**", ""] + [f"- `{r['id']}`: {', '.join(r[field])}" for r in rows[:25]] + [""]
    if errors:
        lines += ["**Errors:**", ""] + [f"- `{r['id']}`: {r['error']}" for r in errors[:10]] + [""]
    return "\n".join(x for x in lines if x is not None)


def _version() -> str:
    """The code a scorecard was produced from; "-dirty" means uncommitted changes."""
    try:
        return subprocess.run(["git", "describe", "--always", "--dirty"], cwd=ROOT, capture_output=True,
                              text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def main() -> None:
    version = _version()
    ap = argparse.ArgumentParser()
    ap.add_argument("tiers", nargs="*", default=["a"])
    ap.add_argument("--workers", type=int, default=max(1, min(8, (os.cpu_count() or 2) // 2)))
    args = ap.parse_args()
    sections = []
    if "a" in args.tiers:
        cases = yaml.safe_load((ROOT / "eval" / "tier_a.yaml").read_text(encoding="utf-8"))
        sections.append(summarize("a", run_tier("a", cases, args.workers)))
    if "b" in args.tiers:
        sections.append(summarize("b", run_tier("b", tier_b.cases(), args.workers)))
    # Tier C (simulated conversations, eval/tier_c.py) is written separately: keep it.
    old = SCORECARD.read_text(encoding="utf-8") if SCORECARD.exists() else ""
    tier_c = "\n## Tier C:" + old.split("## Tier C:", 1)[1] if "## Tier C:" in old else ""
    SCORECARD.write_text(
        f"# Scorecard\n\nGenerated by `eval/run.py` on {date.today()} from `{version}` (don't edit by hand). "
        "Each household is interviewed by the Question Engine with an oracle answering from its full truth; "
        "the first results, and the results after checking every \"maybe\", are compared with the full-information "
        "result.\n\n"
        + "\n".join(sections) + tier_c, encoding="utf-8")
    print(f"-> {SCORECARD}")


if __name__ == "__main__":
    main()
