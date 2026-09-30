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
| 4 | MCP server + Alexa+ simulator | Oct 9 – Oct 15 | A full screening works end to end by voice in the Unclaimed Alexa+ simulator (web app) against the deployed MCP server |
| 5 | Action plans + screen (MCP App) | Oct 12 – Oct 18 | Every result links to a verified plan card that renders in the simulator's Echo Show frame |
| 6 | Harden and polish | Oct 17 – Oct 21 | The scorecard is stable; a fresh clone runs from the README; friction log written |
| 7 | Demo and submit | Oct 20 – Oct 23 | Submitted on Devpost (Alexa+ track + AWS Builder mini-challenge) |

## Stage 0: Setup and de-risk (Sep 30 – Oct 2)
- [x] Join the hackathon on Devpost (done Sep 30)
- [ ] Create the Devpost project (draft) and pick the Alexa+ track + both mini-challenges
- [x] Windows: install WSL2 + Ubuntu (the Alexa+ CLI supports macOS/Ubuntu only); Node 24+ inside Ubuntu (Ubuntu 26.04, Node 24.21 via nvm, AWS CLI 2.37; Sep 30)
- [ ] AWS account + request hackathon AWS credits (https://forms.gle/GaHFxSbBQNG9Kti6A); enable Amazon Bedrock model access (account created, us-east-1; credits pending; Bedrock not yet checked)
- [ ] Amazon developer account; install the `alexa-ai` CLI; read the Alexa+ MCP quickstart (account done; IAM user `alexa-ai-tools` created, AWS account 810995308352, but Amazon's `AddOn3PDeveloperToolsRead` role denies our account: the add-on tooling is allowlist-only. The track only requires a self-hosted MCP server (spec 2025-11-25+, Streamable HTTP) or a simulated Alexa+ web app. See friction log)
- [ ] Repo skeleton, license, CI (skeleton + AGPL license public at https://github.com/shiva-shivanibokka/unclaimed; CI not yet)
- [ ] "Hello" MCP server (TypeScript, Streamable HTTP) deployed on AWS (built and smoke-tested locally Sep 30: warm calls 2–7 ms; not yet deployed)
- [x] Decide the demo path (Sep 30): no Amazon device and no add-on access, so we submit a **self-hosted MCP server** (verified: negotiates protocol `2025-11-25` over Streamable HTTP) **plus a simulated Alexa+ experience** (web app), both allowed by the Alexa+ track rules. If Amazon allowlists account 810995308352 later, we also deploy the same server as a real add-on
- [ ] Ask Amazon for add-on allowlisting (office hours / Developer Community forum). Optional, never on the critical path
- [ ] **Answer:** is the 500 ms round-trip limit enforced as a timeout? On which calls?
  - Docs (MCP quickstart): "Your MCP server must meet a round-trip query response latency of less than 500 ms." No page says whether it's a hard timeout, a certification check, or which MCP methods it covers.
  - To test live: the `hello` tool takes `delay_ms`; call it from the simulator at 300 / 600 / 1500 / 5000 ms and record which ones fail.
- [ ] **Answer:** is OAuth sign-in mandatory for an add-on that stores no user data?
  - Docs answer: **no user sign-in needed.** "Account linking is optional"; only enable it "if your tools genuinely require user identity" (MCP Account Linking page). The quickstart's "Required: OAuth 2.1 ... PKCE" applies only if you do enable linking.
  - Still open: Tier 1 service auth (`client_credentials`, M2M) is described as "if you have a private MCP Server". Confirm on first deploy that a public, auth-less server is accepted (`alexa-ai new mcp` asks "Does your Add-on require account linking? (Y/N)" → answer N).
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
- [ ] Deploy the MCP server publicly (free, no login: judges must be able to test it)
- [ ] Unclaimed Alexa+ simulator (web app): browser speech in/out, Echo Show-style frame, a Strands agent on Bedrock acting as the Alexa+ orchestrator and calling our MCP server over Streamable HTTP; rate-limited so public judge access can't run up the Bedrock bill
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
- Mini-challenge 1: AWS Builder. It requires Bedrock / AgentCore / Strands / Kiro / SageMaker with documented integration (plain hosting does not count). Plan: the same Strands agent on Bedrock powers both the public simulator and the Tier C test harness (plus an LLM playing the person); consider hosting the MCP server on AgentCore Runtime if latency allows.
- Mini-challenge 2: Open Source. It requires a NEW additional open-source project or a PR to a public repo. Plan: publish the Question Engine as a standalone library (generic calculator interface), and/or upstream fixes to PolicyEngine-US.
- One project can win at most 1 track prize + 1 mini-challenge prize; entering both mini-challenges doubles the chances.

## Stage 7: Demo and submit (Oct 20 – Oct 23)
- [ ] Demo video under 3 minutes (strongest moment first)
- [ ] Devpost: description, repo, video, product feedback, friction log, track + mini-challenge
- [ ] Submit by the evening of Oct 22
