# engine

Python service that runs [PolicyEngine-US](https://github.com/PolicyEngine/policyengine-us) (pinned: `policyengine-us==2.18.2`) for one household and reports every in-scope program for CA and IL. The code does all the arithmetic and makes every eligibility decision; the AI only phrases questions.

- `unclaimed_engine/household.py`: input schema, already in engine units (yearly income; the MCP server converts from paychecks)
- `unclaimed_engine/programs.py`: the programs we screen for, mapped to PolicyEngine variables
- `unclaimed_engine/calculate.py`: household → PolicyEngine situation → per-program results + assumptions
- `unclaimed_engine/geo.py` + `data/zip_county.csv`: ZIP → county (HUD USPS crosswalk, residential-address weighted)
- `unclaimed_engine/app.py`: FastAPI (`GET /health`, `GET /programs`, `POST /calculate`, schema at `/openapi.json`), warmed up at startup
- `tests/`: results vs. official published figures (USDA, IRS, state law), and the API contract
- `scripts/measure_latency.py`: warm latency per household shape and per program

The Question Engine (`question_engine/`) arrives in Stage 3.

## Run (Linux / WSL)

PolicyEngine-US has file paths longer than Windows' 260-character limit, so on Windows run it inside WSL. Keep the virtualenv on the Linux filesystem, which is much faster than `/mnt/c`:

```bash
export UV_PROJECT_ENVIRONMENT=~/.venvs/unclaimed-engine
uv sync
uv run pytest                                   # ~25 s, most of it the engine's cold start
uv run uvicorn unclaimed_engine.app:app --port 8000
uv run python scripts/measure_latency.py
```

```bash
curl -s localhost:8000/calculate -H 'content-type: application/json' -d '{
  "state": "CA", "county": "LOS_ANGELES_COUNTY_CA", "rent": 21600,
  "people": [
    {"id": "you", "relationship": "head", "age": 34, "employment_income": 32000},
    {"id": "kid1", "relationship": "child", "age": 4},
    {"id": "kid2", "relationship": "child", "age": 9}
  ]}'
```

## Contract

- **Known vs. unknown.** Every optional field is a value or `null`/missing. Unknown fields aren't sent to PolicyEngine, which would silently default them (0, false, citizen, the first county in the state). The defaults actually used come back in `assumptions`, so nothing is assumed invisibly. "Declined" is tracked by the caller (Stage 2).
- **Periods.** Screening date `as_of` (default today). Monthly programs are calculated for that month, yearly ones for that calendar year (tax credits = the return filed the next spring).
- **Eligibility.** Where PolicyEngine has a flag that fully decides eligibility (income tests included), `eligible` comes from it; otherwise `eligible` means amount > 0 (tax credits, SSI, ACA credit, whose flags skip the income phase-out). So a household can be `eligible` with `amount` 0 when the amount depends on a bill we haven't asked (Lifeline, CARE, child care).
- **Why (`explain`).** Each program returns the engine facts behind its result: eligibility tests passed or failed, income as a share of the poverty line, maximum benefits, limits. `label`, `unit` and `period` come from PolicyEngine; person-level facts come `by_person`. The engine never writes sentences: the AI phrases these facts for the person, so nothing is retyped.
- **Amounts.** `amount` is per `per` (tax credits per year, everything else per month); `monthly_value` puts every program on one scale for the Question Engine. Medicaid and CHIP report `eligible_people` rather than dollars, because the engine's value is the cost of coverage, not cash.
- **County.** A given `county` wins. Otherwise the ZIP is used: if one county holds ≥ 95% of the ZIP's residential addresses it is used, else `county` is null and `county_candidates` lists the options to ask about. Refresh the data each quarter: `HUD_API_TOKEN=... uv run python scripts/build_zip_county.py`.
- **Single source of truth.** Allowed immigration statuses, county names and the defaults reported in `assumptions` are read from PolicyEngine at startup, not copied. Supported states are defined once, in `programs.py`. Other components read `/programs` and `/openapi.json` rather than re-typing them.
- **Household shape (v1).** One head, an optional spouse, and children, in one tax unit. Other adults (grandparents, roommates) aren't supported yet.
- **Privacy.** Nothing is stored; logs carry only the state, the number of people and the timing.

## Measured (Sep 30, 2026; i7-13700HX, WSL2, warm)

| | |
|---|---|
| Warm-up (cold start + first calculation of each program) | 5.7 s |
| Full screening incl. `explain`, 6 household shapes, median | 419–457 ms |
| Full screening, worst of 5 runs | ~1.1 s (about one run in five spikes) |
| Single program in a fresh simulation | EITC / CalEITC / YCTC ≤ 5 ms · SNAP 129 ms · CTC, ACA, Medicaid, CHIP ~210 ms · CARE / FERA / Lifeline ~350 ms |

A full screening doesn't fit a 500 ms turn budget on its own once the Question Engine adds what-ifs, so Stage 3 needs batching (many variants in one simulation) and computing ahead while the person answers.

## Known engine limitations (handled in wording and plans, not hidden)

- **SNAP work rule (H.R.1).** Adults 18–64 without dependents must work 20 h/week (`weekly_hours_worked`). The engine treats a non-working adult as ineligible right away, but the law allows 3 countable months of SNAP in 36 before that (7 CFR 273.24(b)). The result must say "you can likely get SNAP for up to 3 months" rather than "not eligible".
- **Cash aid counts as SNAP income.** A zero-income family gets CalWORKs / TANF, which lowers SNAP. This is correct, but it assumes they receive the cash aid.
- **Discount amounts depend on bills we don't ask yet.** Lifeline, CARE/FERA and child-care amounts scale with phone, electricity and child-care costs, which PolicyEngine defaults to $0 when unknown (not listed in `assumptions`, because they aren't in our schema). Stage 2's coverage checker finds every such defaulted input and turns it into a question or a stated assumption.
- **California LIHEAP** is not modeled (only Riverside County's), so it appears in plans, not in calculations.
