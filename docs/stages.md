# Build stages

Deadline: **Friday Oct 23, 2026, 12:00 PM PDT** (1:00 PM MDT). Target submission: **evening of Oct 22** (one day of buffer).
Judging: Nov 9–20 · winners around Dec 3.

Stages overlap on purpose. The riskiest unknowns are answered first. Each stage has a "done when" check; we don't move on until it passes.

| # | Stage | Dates | Done when |
|---|---|---|---|
| 0 | Setup and de-risk | Sep 30 – Oct 2 | Alexa+ calls our hello tool; the 500 ms limit and the sign-in requirement both have written answers |
| 1 | Engine service | Oct 1 – Oct 4 | 10 sample households return correct results, with latency measured |
| 2 | Dictionary and coverage | Oct 3 – Oct 8 | The coverage test passes: every input sorted into ask / derive / assume / out-of-scope |
| 3 | Question Engine + eval tiers A and B | Oct 6 – Oct 11 | The first scorecard exists; false "you qualify" = 0 on tier B |
| 4 | MCP server + Alexa+ integration | Oct 9 – Oct 15 | A full screening works end to end in Alexa+ (simulator + real Echo) |
| 5 | Action plans + screen (MCP App) | Oct 12 – Oct 18 | Every result links to a verified plan card that renders on the Echo Show |
| 6 | Harden and polish | Oct 17 – Oct 21 | The scorecard is stable; a fresh clone runs from the README; friction log written |
| 7 | Demo and submit | Oct 20 – Oct 23 | Submitted on Devpost (Alexa+ track + AWS Builder mini-challenge) |

## Stage 0: Setup and de-risk (Sep 30 – Oct 2)
- [x] Join the hackathon on Devpost (done Sep 30)
- [ ] Create the Devpost project (draft) and pick the Alexa+ track + both mini-challenges
- [ ] Windows: install WSL2 + Ubuntu (the Alexa+ CLI supports macOS/Ubuntu only); Node 24+ inside Ubuntu
- [ ] AWS account + request hackathon AWS credits (https://forms.gle/GaHFxSbBQNG9Kti6A); enable Amazon Bedrock model access
- [ ] Amazon developer account; install the `alexa-ai` CLI; read the Alexa+ MCP quickstart
- [ ] Repo skeleton, license, CI
- [ ] "Hello" MCP server (TypeScript, Streamable HTTP) deployed on AWS
- [ ] Test in the Alexa+ web simulator (and on a real Echo if available)
- [ ] **Answer:** is the 500 ms round-trip limit enforced as a timeout? On which calls?
- [ ] **Answer:** is OAuth sign-in mandatory for an add-on that stores no user data?
- [ ] Log every friction point in `docs/friction-log.md`

## Stage 1: Engine service (Oct 1 – Oct 4)
- [ ] FastAPI service wrapping PolicyEngine-US (pinned version); warm on startup
- [ ] Household schema (people, ages, relationships, income, housing, state, ZIP, county)
- [ ] Program list for CA + IL (SNAP/CalFresh, WIC, EITC, CTC, state EITCs, Medicaid/Medi-Cal, CHIP, ACA credit, CalWORKs/TANF, CARE/FERA, LIHEAP, child care, …)
- [ ] "Why you qualify" reasons from the engine's intermediate values
- [ ] ZIP → county crosswalk (HUD USPS)
- [ ] Latency measurements per program

## Stage 2: Dictionary and coverage (Oct 3 – Oct 8)
- [ ] Trace-based coverage checker over generated CA + IL households
- [ ] Classify every read input: ask / derive / assume / out-of-scope
- [ ] Dictionary entries for the 5 core questions and every "ask" follow-up
- [ ] Assumptions list (shown to the user on the results screen)

## Stage 3: Question Engine + eval tiers A and B (Oct 6 – Oct 11)
- [ ] Candidate listing (applies_when, requires)
- [ ] Batched what-ifs; scoring (flips ≫ dollars ÷ cost); stop rule (no flip, < $25/mo)
- [ ] Think-ahead cache for latency
- [ ] Tier A: 30–50 handwritten households
- [ ] Tier B: generator (pairwise coverage + every cutoff ±$1), thousands of households
- [ ] Scorecard v1

## Stage 4: MCP server + Alexa+ integration (Oct 9 – Oct 15)
- [ ] Tools: start_screening, answer, get_results, get_plan
- [ ] Answer schemas (amount + frequency + before/after taxes), validation, conversion, read-back
- [ ] Sign-in (only if required)
- [ ] Deploy; simulator + device testing
- [ ] Tier C: 40–60 simulated conversations

## Stage 5: Action plans + screen (Oct 12 – Oct 18)
- [ ] Plan cards per program per state: what, why you, where/how, bring, next, watch out, handoff
- [ ] Every card has source URLs + a last-verified date
- [ ] MCP App: result cards, checklist, QR code

## Stage 6: Harden and polish (Oct 17 – Oct 21)
- [ ] Fix the scorecard's worst cases; latency; error handling
- [ ] Friction log complete; README; architecture doc final

## Prize strategy
- Primary track: Alexa+ (1st place includes the Amazon team meeting)
- Mini-challenge 1: AWS Builder. It requires Bedrock / AgentCore / Strands / Kiro / SageMaker with documented integration (plain hosting does not count). Plan: Tier C test harness = Strands agent on Bedrock that emulates the Alexa+ orchestrator + a simulated person; consider hosting the MCP server on AgentCore Runtime if latency allows.
- Mini-challenge 2: Open Source. It requires a NEW additional open-source project or a PR to a public repo. Plan: publish the Question Engine as a standalone library (generic calculator interface), and/or upstream fixes to PolicyEngine-US.
- One project can win at most 1 track prize + 1 mini-challenge prize; entering both mini-challenges doubles the chances.

## Stage 7: Demo and submit (Oct 20 – Oct 23)
- [ ] Demo video under 3 minutes (strongest moment first)
- [ ] Devpost: description, repo, video, product feedback, friction log, track + mini-challenge
- [ ] Submit by the evening of Oct 22
