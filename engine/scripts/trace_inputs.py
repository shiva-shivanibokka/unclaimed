"""List every PolicyEngine input our programs read over the coverage grid, with how many
households read it, which programs, and its dictionary bucket.

Run: uv run python scripts/trace_inputs.py [out.json]
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from policyengine_us.system import system  # noqa: E402

from unclaimed_engine.coverage import grid, traced_inputs  # noqa: E402
from unclaimed_engine.dictionary import load  # noqa: E402


def main(out: str | None) -> None:
    households = list(grid())
    found = traced_inputs(households)
    buckets = load().buckets()
    rows = [
        {"variable": k, "entity": system.variables[k].entity.key, "period": system.variables[k].definition_period,
         "type": system.variables[k].value_type.__name__, "label": system.variables[k].label,
         "households": v["households"], "programs": sorted(v["programs"]), "bucket": buckets.get(k)}
        for k, v in sorted(found.items(), key=lambda kv: (-kv[1]["households"], kv[0]))
    ]
    unclassified = [r["variable"] for r in rows if not r["bucket"]]
    print(f"{len(households)} households traced; {len(rows)} inputs read; {len(unclassified)} unclassified")
    if out:
        Path(out).write_text(json.dumps(rows, indent=1))
        print(f"-> {out}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
