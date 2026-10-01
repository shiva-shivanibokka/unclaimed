# engine

Python service that runs [PolicyEngine-US](https://github.com/PolicyEngine/policyengine-us) (pinned: `policyengine-us==2.18.2`) for one household and reports every in-scope program for CA and IL. The code does all the arithmetic and makes every eligibility decision; the AI only phrases questions.

- `unclaimed_engine/dictionary.py`: loads `../dictionary/dictionary.yaml`, the single source for every question and every engine input's handling (see `dictionary/README.md`)
- `unclaimed_engine/household.py`: household structure; every answer field is generated from the dictionary (engine units: yearly income; the MCP server converts from paychecks)
- `unclaimed_engine/coverage.py`: traces which engine inputs the programs read, over a grid of households
- `unclaimed_engine/programs.py`: the programs we screen for, mapped to PolicyEngine variables
- `unclaimed_engine/calculate.py`: household → PolicyEngine situation → per-program results + assumptions
- `unclaimed_engine/geo.py` + `data/zip_county.csv`: ZIP → county (HUD USPS crosswalk, residential-address weighted)
- `unclaimed_engine/app.py`: FastAPI (`GET /health`, `GET /programs`, `GET /dictionary`, `POST /calculate`, schema at `/openapi.json`), warmed up at startup
- `tests/`: results vs. official published figures (USDA, IRS, state law), and the API contract
- `scripts/measure_latency.py`: warm latency per household shape and per program
- `scripts/trace_inputs.py`, `scripts/sensitivity_scan.py`: which inputs the programs read, and which change results (evidence for the dictionary)

The Question Engine (`question_engine/`) arrives in Stage 3.

## Run (Linux / WSL)

PolicyEngine-US has file paths longer than Windows' 260-character limit, so on Windows run it inside WSL. Keep the virtualenv on the Linux filesystem, which is much faster than `/mnt/c`:

```bash
export UV_PROJECT_ENVIRONMENT=~/.venvs/unclaimed-engine
uv sync
uv run pytest -m 'not slow'                     # ~30 s
uv run pytest                                   # + the coverage trace, ~15 min
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

- **Known, unknown, declined.** Every answer field is a value or `null`/missing (unknown). Questions the person chose not to answer go in `declined` (`"rent"`, `"a.immigration_status"`): calculated like unknown, reported as declined so they aren't asked again. Unknown and declined answers aren't sent to PolicyEngine, which would silently default them; each comes back in `assumptions` as `{question, person, value, status}` with the engine's actual default (including the county it falls back to). Everything never asked is covered by the dictionary's `assumed` groups, whose plain-language `statements` come back for the results screen. One answer can feed several engine inputs (`is_disabled` also sets SSI's separate disability test). "Declined" is tracked by the caller (Stage 2).
- **Periods.** Screening date `as_of` (default today). Monthly programs are calculated for that month, yearly ones for that calendar year (tax credits = the return filed the next spring).
- **Eligibility.** Where PolicyEngine has a flag that fully decides eligibility (income tests included), `eligible` comes from it; otherwise `eligible` means amount > 0 (tax credits, SSI, ACA credit, whose flags skip the income phase-out). So a household can be `eligible` with `amount` 0 when the amount depends on a bill we haven't asked (Lifeline, CARE, child care).
- **Why (`explain`).** Each program returns the engine facts behind its result: eligibility tests passed or failed, income as a share of the poverty line, maximum benefits, limits. `label`, `unit` and `period` come from PolicyEngine; person-level facts come `by_person`. The engine never writes sentences: the AI phrases these facts for the person, so nothing is retyped.
- **Amounts.** `amount` is per `per` (tax credits per year, everything else per month); `monthly_value` puts every program on one scale for the Question Engine. Medicaid and CHIP report `eligible_people` rather than dollars, because the engine's value is the cost of coverage, not cash.
- **County.** A given `county` wins. Otherwise the ZIP is used: if one county holds ≥ 95% of the ZIP's residential addresses it is used, else `county` is null and `county_candidates` lists the options to ask about. Refresh the data each quarter: `HUD_API_TOKEN=... uv run python scripts/build_zip_county.py`.
- **Single source of truth.** Allowed immigration statuses, county names and the defaults reported in `assumptions` are read from PolicyEngine at startup, not copied. Supported states are defined once, in `programs.py`. Other components read `/programs` and `/openapi.json` rather than re-typing them.
- **Household shape (v1).** One head, an optional spouse, and children (each younger than the head). Tax roles come from `relationship`, never from PolicyEngine's age-based guess (which would make an 18-year-old the spouse). Children under 19, full-time students under 24, or disabled children are dependents; other adult children file their own return. Structural engine inputs (tax unit IDs, household head, own children, FIPS codes, ZIP) are derived from the structure, never left to engine defaults. Other adults (grandparents, roommates) aren't supported yet.
- **Limits.** `as_of` within one year of today (the range the official-figure tests cover; outside it the engine errors or extrapolates). Money fields within ±$10M. A given `county` must contain the given `zip`.
- **Overload.** At most `UNCLAIMED_MAX_IN_FLIGHT` (default 8) calculations running or waiting; beyond that, 503 at once. `ms` is compute time, `wait_ms` the time spent queued. `/health` stays responsive under load. Engine failures return a generic 503 and log only the error type.
- **Privacy.** Nothing is stored; logs carry only the state, the number of people and the timing.

## Measured (Sep 30, 2026, Stage 2: dictionary-driven inputs; i7-13700HX, WSL2, warm)

This table is the only place these numbers live; other docs link here.

| | |
|---|---|
| Warm-up (first calculation of each program, after import) | 5.9 s |
| Full screening incl. `explain`, 6 household shapes, median | 360–396 ms |
| Full screening, worst of 5 runs | ~1.0 s (about one run in five spikes) |
| Single program in a fresh simulation | EITC / CalEITC / YCTC ≤ 5 ms · SNAP 129 ms · CTC, ACA, Medicaid, CHIP ~210 ms · CARE / FERA / Lifeline ~350 ms |

A full screening doesn't fit a 500 ms turn budget on its own once the Question Engine adds what-ifs, so Stage 3 needs batching (many variants in one simulation) and computing ahead while the person answers.

## Known engine limitations (handled in wording and plans, not hidden)

- **SNAP work rule (H.R.1).** Adults 18–64 without dependents must work 20 h/week (`weekly_hours_worked`). The engine treats a non-working adult as ineligible right away, but the law allows 3 countable months of SNAP in 36 before that (7 CFR 273.24(b)). The result must say "you can likely get SNAP for up to 3 months" rather than "not eligible".
- **Cash aid counts as SNAP income.** A zero-income family gets CalWORKs / TANF, which lowers SNAP. This is correct, but it assumes they receive the cash aid.
- **Discount amounts depend on bills.** Lifeline, CARE/FERA and child-care amounts scale with the phone, electricity and child-care bills (dictionary questions); until they're answered the amount is $0 while `eligible` is still reported correctly.
- **California LIHEAP** is not modeled (only Riverside County's), so it appears in plans, not in calculations.
