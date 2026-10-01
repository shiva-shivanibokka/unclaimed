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
- [x] AWS account (Paid plan, 810995308352) · [x] $25 budget alert (`unclaimed-monthly-25`, emails sbokka@sfsu.edu at 50/80/100% actual + 100% forecast) · [x] Bedrock model access in us-east-1 (Sep 30: working with `us.anthropic.claude-haiku-4-5-20251001-v1:0`, `us.anthropic.claude-sonnet-4-6`, `us.anthropic.claude-sonnet-4-5-20250929-v1:0`; Sonnet 5 / 5.5 say "not available for this account" on the new account) · [ ] hackathon credits form
- [x] WSL2 Ubuntu 26.04 with Node 24 (nvm) and AWS CLI v2
- [x] Publish the repo to GitHub: https://github.com/shiva-shivanibokka/unclaimed (public, AGPL-3.0, topics set)
- [x] Hello MCP server (TypeScript, Streamable HTTP, stateless, JSON responses). Verified it negotiates protocol `2025-11-25`; local smoke test: warm calls 2–7 ms
- [x] Hello web simulator (built in Stage 4): Echo Show–style frame, push-to-talk (browser STT/TTS), MCP client with a Strands + Bedrock brain
- [x] Host the simulator + MCP server publicly (free, no login, rate-limited; Stage 4, `infra/`). Judges can't be expected to bring their own Bedrock access to run it locally
- [x] Measure per-turn latency (our MCP server + simulator brain; the real Alexa+ round trip isn't measurable without access); record it (Stage 4 below)
- [x] Log every friction point in `docs/friction-log.md` (5 entries so far)

Decisions and answers (Sep 30):
- **No sign-in / OAuth.** Alexa+ docs: "Account linking is optional"; only needed "if your tools genuinely require user identity". We store nothing about the person, and judges must be able to test without logging in.
- **500 ms:** Alexa+ docs only say the server "must meet a round-trip query response latency of less than 500 ms" (no word on enforcement). We treat it as a per-call budget for our MCP server and measure it; the `hello` tool's `delay_ms` knob stays for testing if access ever opens.
- **No real-Echo bridge.** We have no Amazon device, and the classic-skill bridge is voice-only; the simulator shows more.
- Add-on tooling: our AWS account is denied by Amazon's role (allowlist-only), and the hackathon FAQ says participants won't get it. Not on any path.

## Stage 1: Engine service (Oct 1 – Oct 4)
- [x] FastAPI service wrapping PolicyEngine-US (version pinned in `engine/uv.lock`); warm on startup. Runs in WSL/Linux (Windows path-length limit)
- [x] Household schema (people, ages, relationships, income, hours worked, pregnancy, disability, immigration, rent, child care, state, county); unknown fields are reported as `assumptions`
- [x] Program list for CA + IL: SNAP/CalFresh, WIC, school meals, Lifeline, SSI, EITC, CTC, ACA credit, Medicaid/Medi-Cal, CHIP, CalWORKs, CalEITC, YCTC, CARE, FERA, CA child care, IL TANF, IL EITC, IL CTC, IL LIHEAP, IL CCAP. CA LIHEAP isn't modeled by the engine → plan card only
- [x] Correctness vs. official figures (32 tests total with API, ZIP, explain and consistency checks) (USDA SNAP FY2026 max allotments + benefit formula, IRS 2026 EITC maxima, CTC incl. refundable phase-in, IL EITC = 20% of federal, Medicaid expansion, children's coverage, WIC, the H.R.1 SNAP work rule, API validation)
- [x] Latency measured: numbers in `engine/README.md`
- [x] "Why you qualify" facts: per program, the engine's own eligibility tests and figures (labels and units from PolicyEngine; the AI phrases them). Eligibility comes from the engine's flag where one fully decides it, so "qualifies, amount depends on your bill" is no longer shown as "not eligible"
- [x] ZIP → county crosswalk: HUD USPS 2026 Q2, weighted by residential addresses (`engine/data/zip_county.csv`, rebuilt by `scripts/build_zip_county.py` with `HUD_API_TOKEN`). Auto-assign when one county has ≥ 95% of residences; otherwise return candidates to ask (58 CA / 250 IL ZIPs)

Findings that change later stages:
- The SNAP work rule for adults 18–64 without dependents makes **weekly hours worked** a must-ask question (Stage 2), and results must mention the 3-month allowance the engine ignores.
- Discount amounts (Lifeline, CARE/FERA, child care) depend on bills the engine silently defaults to $0; Stage 2's coverage checker must surface them.
- A full screening already uses most of the 500 ms turn target (see `engine/README.md`), so Stage 3's what-ifs must be batched and computed ahead.

### Stage 0–1 adversarial review (Sep 30)
Independent reviewer (fresh subagent): 2 blockers, 3 majors, 9 minors, all verified and fixed; 46 engine tests pass.
- **Blocker:** tax roles were guessed by PolicyEngine from age, so an 18-year-old child became the spouse (EITC $4,427 instead of $7,082) and a 25-year-old earning child was merged into the parents' return. Now set from `relationship`; adults 19+ file their own return (stated assumption).
- **Blocker:** `is_disabled` didn't reach SSI's separate disability input (defaulted False): a disabled adult with no income showed $0 SSI. Now $994 (2026 federal rate).
- **Major:** school meals counted only the free tier. Now free + reduced.
- **Major:** `as_of` unbounded: 1990 → 500, 2099 → extrapolated benefits. Now within one year of today.
- **Major:** sync `/health` starved under load (9 s) and requests queued without limit. Now async health, bounded in-flight with 503, compute vs. wait time.
- **Minor:** MCP server accepted any `Origin` (spec violation), returned HTML on bad JSON, exposed the `delay_ms` test knob to the model. Fixed (allow-list via `MCP_ALLOWED_ORIGINS`; JSON-RPC parse error; probe behind `UNCLAIMED_LATENCY_PROBE=1`).
- **Minor:** absurd incomes → NaN (now ±$10M limits); county not checked against ZIP (now must contain it); IL households saw "CalFresh" (per-state names); default county hidden (now named, read from the engine); partly circular SNAP test (added a hand-computed IL case: $120); duplicated numbers and version pins in docs and code (one home each).
- Checked and held up: USDA/IRS figures, IL EITC/CTC, period math, ZIP data integrity (no cross-state gaps in HUD's national file), no personal data in logs, MCP 2025-11-25 transport.

## Stage 2: Dictionary and coverage (Oct 3 – Oct 8)
- [x] Trace-based coverage checker over generated CA + IL households (13 shapes incl. infants, seniors on SSI, a disabled child, students, non-citizens and a homeowner; each unanswered and fully answered); `test_coverage.py` fails on any unclassified input
- [x] Classify every read input (`dictionary/dictionary.yaml` is the live source). Evidence: `sensitivity_scan.py` (values on both sides of each default, every enum option, 156 households). Every input that changes a result is asked, derived, or covered by a statement that is true of the default
- [x] Dictionary entries for the 5 core questions (ZIP and household are structure; pay, other income (17 income types asked as one group), housing) and every follow-up, with definition, phrasing guidance, answer type and units, what-if range, applies_when, requires, cost, clarifiers
- [x] Assumptions list: each unanswered question comes back as `{question, person, value, status}`; the `assumed` groups' statements come back for the results screen
- [x] Single source: the engine's API schema is generated from `dictionary/dictionary.yaml`; `GET /dictionary` serves it to the MCP server and Question Engine; enum options come from the engine; ZIP data uses PolicyEngine's own county FIPS table (rebuilt file identical to the Census-based one)
- [x] Known / unknown / declined: `declined` answers are calculated as unknown and reported as declined

Findings:
- Hidden defaults fixed by deriving them: `state_fips` defaulted to California's code (6) for Illinois households; `is_household_head`, `own_children_in_household`, tax unit IDs and `county_fips` defaulted wrong. None changed a result in the grid today, but they're now correct by construction.
- Full-time students under 24 are now dependents (IRC 152), replacing the Stage 1 stated assumption.
- Tracing is slow per household, so the sensitivity scan batches ~300 variants of a household into one simulation (all 42 households in minutes instead of ~7 hours). Stage 3's what-ifs should use the same batching.

### Stage 2 adversarial review (Sep 30)
Independent reviewer: 1 blocker, 6 majors, 8 minors, all verified and fixed; regression tests in `engine/tests/test_answers.py`.
- **Blocker:** immigration status never reached `ssn_card_type`, which federal EITC/CTC read: an undocumented parent was shown ~$6.1k of credits they can't get. Now derived from immigration status (undocumented: no SSN; other non-citizen statuses: SSN valid for work); CalEITC (ITIN allowed) unaffected.
- **Major:** medical costs were placed on the head, so SNAP's elderly/disabled medical deduction was lost ($24 vs $90/mo). Now asked per person; household answers on per-person inputs need an explicit `on_person` placement (loader-enforced).
- **Major:** CARE/FERA denied to renters with heat in the rent who pay their own electric bill. `tenant_pays_utilities` now follows the electricity/gas bills.
- **Major:** non-citizen defaults (5 years in the US, 40 work quarters) silently granted Medicaid/SSI. Now asked (`years_in_us`, `work_quarters`).
- **Major:** "no special circumstances" statement was false for two defaults: no kitchen (cut a CA senior's state supplement) and WIC nutrition risk = yes. Kitchen now derived True and stated; WIC and SSDI-months have their own statements.
- **Major:** the sensitivity scan only tested one direction and skipped enums. Now both directions + every enum option; re-run over 156 households.
- **Major:** owners' property tax/insurance and the gas bill weren't askable. Added; part-time college students added from the re-run scan.
- **Minor:** tax unit IDs started at 0 (= "no claiming unit" to the engine), now from 1; dependent ages read from the engine's IRS parameters; entity names from the engine; `UNSPECIFIED` enum values never offered; savings is a household total; `declined` rejects empty prefixes and duplicates; CHIP take-up classified; duplicated figures removed from docs.
- Known for Stage 3: an employed adult with unknown hours gets $0 SNAP (hours default 0 fails the work rule), so hours is high-value, and "estimate now" must say SNAP depends on it.

## Stage 3: Question Engine + eval tiers A and B (Oct 6 – Oct 11)
- [x] Candidate listing (applies_when, requires; value conditions such as "rent only for renters"); core questions first; related questions asked household-wide in one breath (other income, disability)
- [x] Batched what-ifs; scoring (flips ≫ dollars ÷ cost); stop rule (no candidate flips anything and every swing < $25/mo). Generic library: `engine/question_engine/` (no benefits knowledge; its own README and tests)
- [x] Think-ahead cache for latency (`POST /next`): computes the likely next households in the background
- [x] Tier A: 32 handwritten CA + IL households (`eval/tier_a.yaml`)
- [x] Tier B: generator (pairwise coverage + every cutoff ±$1): 360 households. Pairwise needs 56 and every cutoff ±$1 needs 304; thousands of random households would add run time, not coverage
- [x] Scorecard v1: `docs/scorecard.md` (generated by `eval/run.py`; numbers live only there). Both tiers: 0 false "you qualify", 0 missed

Findings:
- Declining a question that decides eligibility (e.g. immigration status → federal EITC) now makes the program **conditional** ("if you have an SSN valid for work"), not "you qualify" (`conditional` in `/calculate` and `/next`).
- A gig worker was never asked hours (it required job wages), so SNAP's work rule failed them. Hours is now asked whenever it changes a result.
- The eval only accepts households that can exist: an answer to a question that doesn't apply (Social Security retirement at 50, work hours at 70) is an error, and the generator gives only answers allowed at that age (from the dictionary). The first Tier B run had 2 false "you qualify": one was such a household (retirement benefits at 50, never asked, correctly); the other (pair-027) didn't reproduce alone, in sequence, after the cutoff sweep, under 8 hash seeds or in a full rerun, and that run started the same minute as the last dictionary edit. The scorecard now records the commit it ran on.
- Decision time is above the 500 ms turn target (median and p95 in the scorecard). Think-ahead hides it when the answer is one of the likely ones; Stage 4 measures the real turn, and Stage 6 works on the slow cases.

### Stage 3 adversarial review (Oct 1)
Independent reviewer: 1 blocker, 6 majors, 6 minors, all verified; fixed or accepted below. The reviewer's households are now Tier A cases; regression tests in `test_interview.py`, `test_api.py`, `test_question_engine.py`.
- **Blocker:** answers above a question's high what-if were invisible. IL single at $32K paying $15K/yr child support: SNAP and Lifeline missed, never asked (the high was $6K; SNAP opens near $7K). The high is now defined as a realistic maximum and **checked**: `test_what_if_ranges.py` (slow) finds any flip between the high and twice it across the coverage grid, wherever the amount is plausible (an expense at most half of pay; savings always). It found more: savings $15K → $200K (IL elderly/disabled Medicaid, CalWORKs with a disabled member, CA's 2026 Medi-Cal asset test), medical $3K → $24K, child care $12K → $24K, child support paid → $24K, other incomes → $60K (they only matter for declined answers: they're asked up front).
- **Major:** declining "rent or own?" meant rent was never asked (SNAP missed). A declined prerequisite now counts as met ("if you rent, how much?").
- **Major:** results were compared per household only, so a spouse declining immigration status kept a flat Medicaid "yes" through the child. Programs decided per person (Medicaid, CHIP, WIC) are now compared and scored per person (`medicaid:b`), in the Question Engine, `conditional`, and the eval. Declined multiple-choice answers are tried at every option, not just two.
- **Major:** a split ZIP ran every what-if in the engine's default county. `/next` now asks the county first (with the ZIP's counties as options); the Tier A split-ZIP case was vacuous before (both sides defaulted) and now has a true county.
- **Major:** one request could hold the engine ~9 s (12 people × 401 declined). `declined` is capped at 20. Large households remain slower (12 people ≈ 2.8 s per decision); accepted, measured again in Stage 6.
- **Major:** a real request could wait behind a think-ahead guess, and the guess queue was unbounded. Guesses now run only when no real request is waiting, and only for the latest request; `/next` reports `wait_ms`. A real request can still wait for one guess already running.
- **Major:** Tier B never varied the inputs where early stops go wrong. Added: deductions above the old highs, mixed-status and disabled spouses, declined answers, pregnancy, utilities; the generator only gives answers that can exist (dictionary `applies_when`). The scorecard now shows amount error p95 and max, not just the median.
- **Found while verifying (not in the review):** Illinois LIHEAP (~$100/mo) needs the heating type and the energy bills together; tried one at a time, each changed nothing, so the interview stopped without asking. Questions asked together are now tried together (`Candidate.together` in the library), and the utility questions (heating type, energy, phone and internet bills) are one group. The remaining large amount errors in the scorecard are all households with a declined answer, where the amount is genuinely unknown and reported as an assumption.
- **Minor, fixed:** child care not asked for a disabled teen (gate now "child under 13 or disabled"); think-ahead cache keyed without the date when none is given (now keyed by today); tests and generator retyped dictionary facts (now read from it); simulator docstring wrong about defaults.
- **Minor, accepted:** many sub-$25 swings can add up (by design each unasked question moves less than $25/mo; the scorecard reports the total error); `Candidate.together` was pass-through (now used: see above).
- Held up: batching isolation (batched = unbatched for diverse households), pregnancy, working grandparent, SSDI, large savings, CA child support, API error paths, no household data in logs, the library has no domain knowledge.

## Stage 4: MCP server + Alexa+ integration (Oct 9 – Oct 15)
- [x] Tools: start_screening, answer, get_results. get_plan moves to Stage 5 (it reads the plan cards)
- [x] Answer schemas (amount + frequency + before/after taxes), validation, conversion, read-back
- [x] Sign-in: not required (account linking is optional for Alexa+; nothing is stored)
- [x] Deploy the MCP server publicly (free, no login: judges must be able to test it): ECS Express Mode, `infra/deploy.sh`
- [x] Unclaimed Alexa+ simulator (web app): browser speech in/out, Echo Show-style frame, a Strands agent on Bedrock acting as the Alexa+ orchestrator and calling our MCP server over Streamable HTTP; rate-limited so public judge access can't run up the Bedrock bill
- [ ] Tier C: 40–60 simulated conversations. Runs end to end (`eval/tier_c.py`; first 3 cases: 0 false "you qualify", 0 missed); the full run waits on a Bedrock quota increase (Claude Haiku 4.5 is at 10 requests/minute on this account; support case filed Oct 1)

Latency (Oct 1; the real Alexa+ round trip isn't measurable without access):
- Simulator turn: ~1.5 s per model call; a turn that calls a tool is two calls, ~3.4 s, of which the MCP tool is ~15 ms when the engine's think-ahead already has the answer.
- MCP `answer`, scripted screening with no pause between answers (the worst case: think-ahead never gets a head start): median 0.8 s locally, 2.3 s on AWS (1 vCPU shared by the engine and its think-ahead). A person takes seconds to answer, which is when think-ahead runs; Stage 6 measures it with realistic pauses and sizes the task.

### Stage 4 adversarial review (Oct 1)
Independent reviewer (code, data and deploy; explicit hard-coding audit): 2 high, 7 medium, a hard-coding list, 4 low; all verified. Fixed unless marked accepted.
- **High:** results gave a flat "you qualify" for programs that hinged on a question not asked yet (an estimate before the questions run out: the engine reads a missing answer as 0/no), and could be computed in the engine's default county. Now `/next` reports, for an early stop, which programs could still change with which unasked question (`unanswered`), and `get_results` marks those programs `conditional_on` alongside declined answers; it gives no results until the essentials (location, pay) are in. After a normal stop nothing unasked can change eligibility (the stop rule), so nothing is added.
- **High:** the simulator's Bedrock bill could be run up with a fabricated history (400 KB resent every turn) and no per-turn caps. Now: history ≤ 150 KB (a long screening is about a third of that), replies capped at 4,096 tokens, at most 6 model calls per turn, and a daily budget of tokens billed at the full rate (new input, cache writes, output) in place of a daily turn count.
- **Medium:** "none of the rest" silently recorded a "no" the person never said (heat not included in the rent). The yes/no answers it fills in are now read back, and the utilities group asks about heat in the rent.
- **Medium:** two partners' take-home pay was converted one at a time, the first seeing the other's pay as $0 (joint taxes understated). Each conversion now starts from the take-home figure and runs again once the other's pay before taxes is known.
- **Medium:** answering a question after declining it made the engine reject the household. An answer now replaces the decline.
- **Medium:** the engine sidecar listened on all interfaces; in AWS it now listens on localhost only (`UVICORN_HOST`).
- **Medium:** an engine failure was reported as "busy, try again", so the model would retry something that fails every time. Failure is now 500 ("retrying won't help"), busy stays 503; unexpected errors no longer echo internal messages.
- **Medium:** deploy image tags could mislabel content (untracked files and the root `.dockerignore` didn't make a build "dirty"), and `SKIP_BUILD` didn't check the image exists (it didn't, once: an infra-only commit pointed at a tag never pushed). Both fixed.
- **Medium, accepted:** one client can keep the single-threaded engine busy for others within its 300 requests/minute. The engine's own slot limit bounds the work; acceptable for a demo, revisited in Stage 6 with load numbers.
- **Hard-coding, fixed:** state names (prompt, tool text: now from the engine's `/programs`); question ids in the MCP server (hourly pay's hours question is now declared in the dictionary as `hours_from`; ZIP/county come from the dictionary's `structure`); the unit list (now from the dictionary's `person_units`); the model id in three places and the rate limits in two (now `simulator/simulator/defaults.env`, read by the simulator, Tier C and `deploy.sh`); the region (from the AWS environment); ports repeated through `deploy.sh` (named once there); the server version (from `package.json`); the results card guessing why an amount is $0; drifting numbers in comments and READMEs.
- **Hard-coding, accepted:** each image's default port in its Dockerfile, and the `uv` version pinned in two Dockerfiles (each image is built on its own).
- **Low, fixed:** person ids containing a dot; "none of the rest" while the county is being asked; read-backs out of order when hours came after pay; the take-home test's IL exemption is now the official $2,925 (IDOR Bulletin FY 2026-15) and the tolerance $5, not $300.
- **Low, accepted:** correcting hours after giving hourly pay doesn't recompute the pay (the model re-sends both, as the tool asks).
- New tests: early-estimate conditions (engine), dictionary `hours_from` validation, dotted person ids, location answers, read-back order (MCP), and the simulator's client identity, rate limit, token budget and history checks.
- Held up: X-Forwarded-For handling on both services, the Origin check, the Bedrock permission scoped to one model, the service-linked-role setup, no circular tests.

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
