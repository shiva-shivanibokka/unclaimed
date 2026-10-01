# dictionary

`dictionary.yaml` is the single source for every fact Unclaimed can be told, and for how every PolicyEngine input our programs read is handled. The engine loads and validates it at startup (`engine/unclaimed_engine/dictionary.py`) and generates its API schema from it; the MCP server and the Question Engine read it from the engine (`GET /dictionary`). Nothing else lists questions.

## Buckets

Every engine input the in-scope programs read is in exactly one:

| Bucket | Meaning | Where it's implemented |
|---|---|---|
| `questions` | Asked. Each entry: `id`, `entity` (person/household), `engine` (inputs it sets), `definition`, `ask` (phrasing guidance for the AI), `answer` (type, units, limits), `what_if` (none and a realistic maximum for the Question Engine; checked by `test_what_if_ranges.py`), `applies_when`, `requires`, `cost` (1 easy … 5 sensitive), `clarifiers`, `group`, `core` | The engine's `Household` / `Person` fields |
| `derived` | Set by our code from the household's structure or another answer, or a value we choose over a misleading engine default (e.g. the home has a kitchen) | `DERIVERS` in `engine/unclaimed_engine/calculate.py` |
| `assumed` | Left at PolicyEngine's default (read from the engine). Groups carry a `statement` said out loud on the results screen, which must be true of the default | Nothing to implement; the default is the engine's |
| `out_of_scope` | Only relevant to places or data we don't cover | — |

Enum answers list no values here: they come from the engine variable (e.g. immigration status, heating type).

## How it's checked

- `engine/tests/test_coverage.py` traces every program over a grid of CA + IL households (each unanswered and fully answered) and fails if any input read isn't classified.
- `engine/tests/test_dictionary.py`: every `derived` input has code and vice versa; no input in two buckets; the API schema matches the questions; questions are complete.
- The loader rejects unknown engine variables, wrong entities, unknown `applies_when` keys, `requires` that name no question, and a household answer on a per-person engine input without an explicit `on_person` placement.
- `engine/tests/test_answers.py`: each answer reaches the engine input the programs actually read (e.g. immigration status reaches the SSN check federal credits use; medical costs land on the elderly or disabled member).

## Evidence for the buckets

`engine/scripts/sensitivity_scan.py` sets each input to values on both sides of the engine's default (zero and realistic amounts, the other boolean, every enum option) across CA + IL households, and records which program results change. Inputs that change results for real households are asked; rare ones are assumed with a statement. Results of each run are logged in `docs/stages.md`. Re-run after a PolicyEngine upgrade:

```bash
uv run python scripts/trace_inputs.py trace.json      # inputs read + their bucket
uv run python scripts/sensitivity_scan.py trace.json sensitivity.json
```
