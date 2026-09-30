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

## Engine facts (measured on policyengine-us 2.18.2; Stage 1 pins 2.18.2, whose re-measured numbers are in `engine/README.md`)
- 6,185 variables, 925 of them inputs. Anything not provided silently falls back to a default: usually 0/false, but county defaults to the first county in the state (Alameda CA / Adams IL) and immigration status defaults to citizen.
- Income inputs are yearly; SNAP and WIC outputs are monthly. Medicaid/CHIP output is the value of coverage, not cash.
- Cold start ~14s (+~5s on the first calculation of each program), so the engine must be always-on, not serverless.
- Warm, one household: EITC/CTC ~70 ms; SNAP ~350 ms; ACA ~500 ms; Medicaid 0.8–3 s; all programs ~0.6–0.9 s.
- Batching: 25 income variants in 0.3 s; 32 households in ~0.8 s.
- Tracing: a CA single parent + 2 kids read 283 defaulted inputs.
- County matters: ACA credit for a single 55-year-old at $45K is $6,610 in LA, $10,912 in Alameda (the default) and $13,221 in Modoc.
- Example follow-up sensitivity (CA, LA, parent + kids 4 and 9): at $48K, child care flips SNAP from $0 to $4,920 and job insurance flips the ACA credit from $3,084 to $0. At $32K, job insurance changes nothing.

## Alexa+ constraints
- Round-trip response under 500 ms ("must"; scope to be confirmed in Stage 0)
- OAuth 2.1 + PKCE appears required (to be confirmed in Stage 0)
- Client capabilities: roots only (no elicitation, sampling or push notifications)
- MCP Apps supported for screen UI; US only

## Eval
- Tier A: 30–50 handwritten households
- Tier B: thousands of generated households (pairwise + every cutoff ±$1; counties grouped by rule region)
- Tier C: 40–60 simulated conversations (an LLM plays the person, plus an Alexa+ emulator)
- Scorecard: match vs the full-information answer, questions asked, false "you qualify" (target 0), latency

## Reuse
The Question Engine targets a generic calculator interface, so the same code can drive a mortgage quick-apply document-requirements interview.
