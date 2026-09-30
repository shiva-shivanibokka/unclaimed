# Build stages

Deadline: **Friday Oct 23, 2026, 12:00 PM PDT** (1:00 PM MDT). Target submission: **evening of Oct 22** (one day of buffer).
Judging: Nov 9–20 · winners around Dec 3.

Stages overlap on purpose. The riskiest unknowns are answered first. Each stage has a "done when" check; we don't move on until it passes.

| # | Stage | Dates | Done when |
|---|---|---|---|
| 0 | Setup and de-risk | Sep 30 – Oct 2 | Our web simulator (Strands + Bedrock brain) calls the hello MCP tool by voice; latency measured |
| 1 | Engine service | Oct 1 – Oct 4 | 10 sample households return correct results, with latency measured |
| 2 | Dictionary and coverage | Oct 3 – Oct 8 | The coverage test passes: every input sorted into ask / derive / assume / out-of-scope |
| 3 | Question Engine + eval tiers A and B | Oct 6 – Oct 11 | The first scorecard exists; false "you qualify" = 0 on tier B |
| 4 | MCP server + Alexa+ simulator | Oct 9 – Oct 15 | A full screening works end to end by voice in the Unclaimed Alexa+ simulator (web app) against the deployed MCP server |
| 5 | Action plans + screen (MCP App) | Oct 12 – Oct 18 | Every result links to a verified plan card that renders in the simulator's Echo Show frame |
| 6 | Harden and polish | Oct 17 – Oct 21 | The scorecard is stable; a fresh clone runs from the README; friction log written |
| 7 | Demo and submit | Oct 20 – Oct 23 | Submitted on Devpost (Alexa+ track + AWS Builder mini-challenge) |

## Stage 0: Setup and de-risk (Sep 30 – Oct 2)
> **Change (Sep 30):** the hackathon FAQ says Alexa+ developer tools (MCP Toolkit, `alexa-ai` CLI, Web Simulator) are partner-only. We build a self-hosted MCP server + our own web simulator. Hosting is optional; a locally runnable public repo + demo video is enough.
- [x] Join the hackathon on Devpost
- [x] Amazon Developer account
- [x] AWS account (Paid plan, 810995308352) · [x] $25 budget alert (`unclaimed-monthly-25`, emails sbokka@sfsu.edu at 50/80/100% actual + 100% forecast) · [ ] Bedrock model access in us-east-1 (Sep 30: calls blocked while the new AWS account is being verified) · [ ] hackathon credits form
- [x] WSL2 Ubuntu 26.04 with Node 24 (nvm) and AWS CLI v2
- [x] Publish the repo to GitHub: https://github.com/shiva-shivanibokka/unclaimed (public, AGPL-3.0, topics set)
- [x] Hello MCP server (TypeScript, Streamable HTTP, stateless, JSON responses). Verified it negotiates protocol `2025-11-25`; local smoke test: warm calls 2–7 ms
- [ ] Hello web simulator: Echo Show–style frame, push-to-talk (browser STT/TTS), MCP client with a Strands + Bedrock brain
- [ ] Host the simulator + MCP server publicly (free, no login, rate-limited). Judges can't be expected to bring their own Bedrock access to run it locally
- [ ] Measure per-turn latency (our MCP server + simulator brain; the real Alexa+ round trip isn't measurable without access); record it
- [x] Log every friction point in `docs/friction-log.md` (5 entries so far)

Decisions and answers (Sep 30):
- **No sign-in / OAuth.** Alexa+ docs: "Account linking is optional"; only needed "if your tools genuinely require user identity". We store nothing about the person, and judges must be able to test without logging in.
- **500 ms:** Alexa+ docs only say the server "must meet a round-trip query response latency of less than 500 ms" (no word on enforcement). We treat it as a per-call budget for our MCP server and measure it; the `hello` tool's `delay_ms` knob stays for testing if access ever opens.
- **No real-Echo bridge.** We have no Amazon device, and the classic-skill bridge is voice-only; the simulator shows more.
- Add-on tooling: our AWS account is denied by Amazon's role (allowlist-only), and the hackathon FAQ says participants won't get it. Not on any path.

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
