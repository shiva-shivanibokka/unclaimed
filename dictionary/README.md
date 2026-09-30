# dictionary

`dictionary.yaml` is the single source for every fact Unclaimed can be told, and for how every PolicyEngine input our programs read is handled. The engine loads and validates it at startup (`engine/unclaimed_engine/dictionary.py`) and generates its API schema from it; the MCP server and the Question Engine read it from the engine (`GET /dictionary`). Nothing else lists questions.

## Buckets

Every engine input the in-scope programs read is in exactly one:

| Bucket | Meaning | Where it's implemented |
|---|---|---|
| `questions` | Asked. Each entry: `id`, `entity` (person/household), `engine` (inputs it sets), `definition`, `ask` (phrasing guidance for the AI), `answer` (type, units, limits), `what_if` (low/high for the Question Engine), `applies_when`, `requires`, `cost` (1 easy … 5 sensitive), `clarifiers`, `group`, `core` | The engine's `Household` / `Person` fields |
| `derived` | Set by our code from the household's structure (or another answer) | `DERIVERS` in `engine/unclaimed_engine/calculate.py` |
| `assumed` | Left at PolicyEngine's default (read from the engine). Groups carry a `statement` said out loud on the results screen | Nothing to implement; the default is the engine's |
| `out_of_scope` | Only relevant to places or data we don't cover | — |

Enum answers list no values here: they come from the engine variable (e.g. immigration status, heating type).

## How it's checked

- `engine/tests/test_coverage.py` traces every program over a grid of CA + IL households (each unanswered and fully answered) and fails if any input read isn't classified.
- `engine/tests/test_dictionary.py`: every `derived` input has code and vice versa; no input in two buckets; the API schema matches the questions; questions are complete.
- The loader rejects unknown engine variables, wrong entities, unknown `applies_when` keys and `requires` that name no question.

## Evidence for the buckets

`engine/scripts/sensitivity_scan.py` sets each input to a realistic non-default value across CA + IL households and records which program results change (Sep 30, 2026: 158 of ~300 inputs change a result for some household). Inputs that change results for real households are asked; rare ones are assumed with a statement. Re-run after a PolicyEngine upgrade:

```bash
uv run python scripts/trace_inputs.py trace.json      # inputs read + their bucket
uv run python scripts/sensitivity_scan.py trace.json sensitivity.json
```
