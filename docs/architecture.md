# Architecture

## Layers (frontend → service → engine)
1. **Frontend:** Alexa+ voice + Echo Show MCP App UI (result cards, document checklist, QR handoff). For the hackathon demo this runs in our simulated Alexa+ web app (a Strands agent on Bedrock as the orchestrator), because add-on tooling is allowlist-only
2. **Service:** MCP server (TypeScript, Streamable HTTP, MCP spec 2025-11-25), stateless. The household draft travels inside tool arguments and results. Validates answers, converts units, reads answers back.
3. **Engine side:** Python (FastAPI), always warm on AWS:
   - **Question Engine**: the brain we own
   - **PolicyEngine-US**: the calculator, pinned version
   - **Dictionary**: YAML, every askable fact
   - **ZIP → county crosswalk**: HUD USPS
   - **Action-plan catalog**: YAML per program per state, with sources
4. **Build and test** (never in the live path): coverage checker, eval harness (tiers A/B/C), scorecard

No database: static data lives in git; results are cached in memory; logs and metrics are anonymous only.

## Question Engine
Chosen: engine-driven questioning, with light rules in the dictionary. Rejected: a hand-written decision tree (brittle, rewritten per state and per rule change) and letting an LLM pick questions (not repeatable or testable). The LLM only phrases questions.

Loop after every answer:
1. Candidates = dictionary questions not yet answered, whose `applies_when` is true and whose `requires` are met
2. What-if: run the engine at each candidate's low and high values, batched in one simulation
3. Score = eligibility flips (heavily weighted) + dollar swing, divided by `cost`
4. If nothing flips and no benefit moves more than ~$25/month → stop and show results
5. Otherwise ask the top question and repeat. No hard cap; after ~10 questions, offer "estimate now or keep going".
6. Think ahead: precompute likely answers while the person responds (the 500 ms limit)

## Dictionary: exhaustive for the programs in scope
Every engine input read by the in-scope programs is sorted into exactly one bucket:
- **Ask:** can change a result for real households
- **Derive:** computed from other answers (county from ZIP, yearly pay from paycheck × frequency)
- **Assume, and say so:** rare for this audience (gambling winnings, farm income); listed on the results screen
- **Out of scope:** only feeds programs we don't cover

The coverage checker traces thousands of generated CA + IL households. The build fails if any read input is unclassified.

Entry fields: `id`, `engine_field`, `entity`, `definition`, `ask`, `answer` schema, `convert`, `what_if_range`, `applies_when`, `requires`, `cost` (1 easy … 5 sensitive), `clarifiers`.

## Engine behavior our design depends on
Measured numbers (latency, warm-up) live only in `engine/README.md`, measured on the pinned version on our machine. This section lists behavior, not measurements.
- 6,185 variables, 925 of them inputs. Anything not provided silently falls back to a default: usually 0/false, but county defaults to the first county in the state and immigration status defaults to citizen. Our layer reports every such default as an assumption.
- Some obvious-looking variables are calculated, not inputs: set `employment_income_before_lsr`, `pre_subsidy_rent`, `spm_unit_pre_subsidy_childcare_expenses`, not `employment_income`, `rent`, `childcare_expenses` (setting those overrides the engine's own formula).
- Tax roles default to an age-based guess (oldest adults become head and spouse), so we always set them from the stated relationships.
- Units: income inputs are yearly; SNAP and WIC are monthly; Medicaid/CHIP output is the value of coverage, not cash.
- Cold start is seconds long, so the engine must be always-on, not serverless.
- County changes results (ACA credit, CalWORKs), so ZIP → county is load-bearing.
- Planning-session findings (`engine/research/`, a different machine, and using the calculated variables above as inputs), to be re-verified with our engine's inputs in Stage 2 and 3 tests: batching many variants in one simulation is far cheaper than separate runs; a CA single parent + 2 kids reads ~283 defaulted inputs; at $48K in LA, child care flips SNAP and job-based insurance flips the ACA credit, while at $32K job insurance changes nothing.

## Alexa+ constraints
Stage 0 answers (sign-in not needed; the 500 ms limit's wording and how we treat it) are recorded once, in `docs/stages.md`.
- Round-trip response under 500 ms ("must", per the MCP quickstart)
- Client capabilities: roots only (no elicitation, sampling or push notifications)
- MCP Apps supported for screen UI; US only

## Eval
- Tier A: 30–50 handwritten households
- Tier B: thousands of generated households (pairwise + every cutoff ±$1; counties grouped by rule region)
- Tier C: 40–60 simulated conversations (an LLM plays the person, plus an Alexa+ emulator)
- Scorecard: match vs the full-information answer, questions asked, false "you qualify" (target 0), latency

## Reuse
The Question Engine targets a generic calculator interface, so the same code can drive a mortgage quick-apply document-requirements interview.
