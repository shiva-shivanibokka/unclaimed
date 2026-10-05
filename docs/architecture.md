# Architecture

```
person ──voice──> Alexa+ (here: the simulator, Amazon Nova 2 Sonic live, run by a Strands BidiAgent)
                     │  MCP over Streamable HTTP (stateless; the household draft rides in every call)
                     ▼
                  MCP server (TypeScript) ── screen (MCP Apps) ──> Echo Show
                     │  HTTP, localhost (same task)
                     ▼
                  engine (Python): Question Engine · PolicyEngine-US · dictionary · ZIP→county · plan cards
```

## Layers
1. **Frontend.** Alexa+ voice, and the Echo Show screen: an MCP App (`ui://unclaimed/screen`) showing the result tiles and each plan with a QR code. Alexa+ add-on tooling is partner-only, so the demo runs in our simulator: an Echo Show-style page where Amazon Nova 2 Sonic (speech to speech, on Bedrock, run by a Strands BidiAgent) hears the person and answers out loud in one stream, so the person can cut in, calling our MCP server the way Alexa+ calls an add-on. It is hands-free after one tap; after some quiet it rests until the wake word. The device keeps the household draft for the open conversation and fills it into each call, as Alexa+ keeps a conversation's context, so the server stays stateless and the speech model never copies it. The page hosts the MCP App per the spec (sandboxed frame, the spec's messages).
2. **MCP server** (`mcp-server/`). Five tools: `start_screening`, `answer`, `check_programs`, `get_results`, `get_plan`. Validates answers, converts the person's units (per paycheck, per hour, take-home) to the engine's, reads answers back for confirmation. Holds no state and no program knowledge: questions, phrasing, units, options, programs and the household schema are read from the engine at startup.
3. **Engine** (`engine/`), always warm (cold start is seconds):
   - **PolicyEngine-US**, pinned: the calculator. Every eligibility decision and amount.
   - **Question Engine** (`engine/question_engine/`): a generic library with no benefits knowledge (it takes candidates and a calculator interface).
   - **The benefits interview** (`interview.py`): the dictionary turned into Question Engine candidates.
   - **Dictionary** (`dictionary/dictionary.yaml`): every askable fact and the handling of every engine input.
   - **ZIP → county**: the HUD USPS crosswalk, weighted by residential addresses.
   - **Plan cards** (`plans/`): per program and state, cited and dated.
4. **Build and test** (never in the live path): the coverage checker, the eval tiers, the scorecard, the research experiments.

No database. Static data lives in git; decisions are cached in memory; logs carry only state, household size and timings.

## The model talks; code decides
The language model phrases questions and explains results; it never chooses what to ask, when to stop, or what anyone qualifies for. Rejected alternatives: a hand-written decision tree (rewritten per state and per rule change) and letting the model pick questions (not repeatable, not testable, and the model can't see which answer would change a result).

**Question Engine loop**, after every answer:
1. Candidates: dictionary questions not answered or declined, whose `applies_when` holds and whose `requires` are met. The essentials (location, who lives there, pay, housing) come first.
2. What-ifs: each candidate at a low and a high realistic answer, all batched into one PolicyEngine simulation. Questions asked together (a group like "other income") are tried together.
3. Score: eligibility flips (weighted far above dollars) plus the dollar swing, divided by the question's cost (how hard or sensitive it is to ask).
4. Short by design (a voice conversation): after the essentials, ask at most a few more questions (`QUICK_QUESTIONS`, the top-scoring one each time), then give results. Programs an unasked question could still flip are shown as "maybe" ("if ..."), never "you qualify".
5. **Checking a maybe:** when the person asks about a "maybe" program, the household's `focus` names it, and the same loop runs on that program alone (what could flip it or move it by the stop threshold), until nothing would; the results then update (a program ruled out leaves the screen). Tuning lives in `interview.py`. With every program in focus this is the full interview the research measures. The scorecard measures the first results and the results after every "maybe" is checked.
6. **Think-ahead:** while the person answers, the likely next households (the asked question answered "no", or its main question "yes") are decided in the background, and once the interview stops the results are computed too. A guess never starts while a real request is waiting; a real request waits at most for the one guess already running.

## Known, unknown, declined
PolicyEngine silently reads anything missing as a default (0/no, the first county in the state, citizen). We never let a default stand in for an answer:
- Answers are known, unknown, or declined; unknown and declined fields are not sent to the engine, and each comes back as an assumption with the engine's actual default.
- Inputs the engine reads that we never ask are covered by statements that are true of the default ("no farm income"), said with the results; the coverage checker fails the build if any input the programs read is unclassified.
- Results that an unasked or declined answer could still change, or that depend on something the calculator can't check (which utility serves the home), say "if ...", never "you qualify". Results aren't given until the essentials are in.
- Structural engine inputs (tax units, household head, FIPS codes) are derived from the stated relationships, never left to the engine's age-based guesses.

## Dictionary: exhaustive for the programs in scope
Every engine input the in-scope programs read is in exactly one bucket: **ask** (changes a result for real households), **derive** (county from ZIP, yearly pay from paycheck × frequency), **assume and say so** (rare for this audience), or **out of scope** (feeds only programs we don't cover). The evidence is a trace of which inputs the programs read over a grid of households, and a sensitivity scan of each input on both sides of its default. Each entry: definition, how to ask, answer type and units, what-if range (a checked realistic maximum), `applies_when`, `requires`, `cost`, clarifiers.

## Plan cards
One card per application (programs applied for together share one), in `plans/<STATE>/` or `plans/US/` when the process is the same everywhere. Ways to apply (a site, a phone line, an office finder) are defined once in `plans/channels.yaml`. A card holds only the agency's process, cited to the agency's pages and dated; names, amounts and rules come from the engine, and the loader rejects a card with a dollar amount or a percentage. Cards past their re-verification age fail the tests; `engine/scripts/check_plan_links.py` opens every link.

## Single source of truth
Facts owned by others (rules, amounts, engine defaults, county names, ZIP data) are read from their owner. Our own decisions (supported states, the program list, tuning) are defined once and everything else reads them: the MCP server and simulator read the engine's `/programs`, `/dictionary`, `/openapi.json` and `/plans`; the simulator's settings live in `simulator/simulator/defaults.env`, which deployment reads too. Test expectations are the one exception: official figures typed in with citations, because a test that reads its answer from the engine can't catch the engine being wrong.

## Engine behavior our design depends on
Pinned by `engine/tests/test_engine_behavior.py`, so an upgrade that changes them fails loudly. Measured numbers live only in `engine/README.md`.
- Missing inputs silently default (county to the first in the state, immigration status to citizen, numbers to 0).
- Some obvious-looking variables are calculated, not inputs (`employment_income`, `rent`, `childcare_expenses`): we set the engine's real inputs.
- Income inputs are yearly; SNAP and WIC are monthly; Medicaid and CHIP report the cost of coverage, not cash.
- County changes results (ACA credit, CalWORKs), so ZIP → county is load-bearing.
- Many variants of one household batch into one simulation, far cheaper than separate runs.

## Alexa+ constraints
- Round trip under 500 ms ("must", per the MCP quickstart). Most answers are served from think-ahead; an exact answer nobody guessed is computed on demand (latency in `docs/stages.md`).
- Client capabilities: roots only (no elicitation, sampling or push notifications), so the server never asks back; everything goes through tool results.
- MCP Apps for the screen; US only. No sign-in: account linking is optional, and we store nothing.

## Hosting
AWS us-east-1, ECS Express Mode (`infra/`): the MCP server with the engine as a localhost-only sidecar in one task, and the simulator in another, each behind a managed load balancer. The simulator is the only part allowed to call Bedrock (one model, Nova 2 Sonic), and its live conversations are limited (at once, per client per hour, minutes per day, length, silence) so public access can't run up the bill.

## Evaluation
- **Tier A:** handwritten CA and IL households, including the cases past reviews broke.
- **Tier B:** generated households: pairwise combinations of the inputs, and every program's income cutoff ±$1.
- **Tier C:** simulated conversations: a model plays the person in everyday words, through the real MCP server, with the text pipeline's Alexa or the live one (Nova 2 Sonic).
- Each is compared with the full-information answer. The headline metric is false "you qualify" (target 0); also programs missed, questions asked, amount error, latency. Results: `docs/scorecard.md`. Research experiments on the design itself: `docs/research-plan.md`.

## Reuse
The Question Engine targets a generic calculator interface (`engine/question_engine/README.md`): the same loop can drive any interview whose outcome a calculator decides, such as a mortgage application's document requirements.
