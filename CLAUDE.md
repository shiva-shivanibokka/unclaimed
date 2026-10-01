# CLAUDE.md: context for coding agents

**Project:** Unclaimed, an Alexa+ benefits screener. Entry for the Amazon Developer Hackathon "Build, Ship, Shape", **Alexa+ track** + AWS Builder and Open Source mini-challenges.
**Deadline:** Oct 23, 2026, 12:00 PM PDT (target submit: evening of Oct 22).
**Read first:** `docs/architecture.md`, `docs/stages.md`. Devpost story draft: `docs/devpost-story.md`.

## First tasks for Claude Code (do these in order, confirm each with the user)
1. **Publish to GitHub.** The repo exists locally with commits on `main` but has no remote yet. Using the user's `gh` CLI (already authenticated on this Windows machine):
   ```powershell
   cd "C:\Users\sbokk\HACKATHONS\AMAZON_DEV_HACKATHON_2026\benefits-screener"
   git status            # must be clean; if .git/index.lock exists and no git process is running, delete it
   gh repo create unclaimed --public --source . --remote origin --push --description "Alexa+ benefits screener: asks only the questions that change the answer, calculates with PolicyEngine-US, hands off a step-by-step plan"
   ```
   Then add topics: `gh repo edit --add-topic alexa-plus,mcp,agentic-ai,policyengine,hackathon`. Report the repo URL to the user.
   The public repo is required for Devpost (and for the Open Source mini-challenge, the license must be visible).
2. **Check WSL.** `wsl -l -v` → expect Ubuntu, VERSION 2. The Alexa+ CLI supports macOS/Ubuntu only, so run Alexa tooling inside WSL (e.g. `wsl -d Ubuntu -- bash -lc "..."`). The repo is at `/mnt/c/Users/sbokk/HACKATHONS/AMAZON_DEV_HACKATHON_2026/benefits-screener` from inside WSL.
3. **Stage 0 (revised Sep 30).** Official hackathon FAQ: participants do **NOT** get Alexa+ developer tools (MCP Toolkit, `alexa-ai` CLI, Alexa+ Web Simulator are partner-only). Required path: a **self-hosted MCP server** per the rules + **our own web-based Alexa+ simulator** to demo it. Hosting is optional ("a locally runnable public repo plus your demo video is enough"). So Stage 0 is:
   - Hello MCP server in `mcp-server/` (TypeScript, Streamable HTTP, MCP 2025-11-25), still built to Alexa+'s published requirements (so it's ready for real Alexa+).
   - Hello version of our **Alexa+ simulator** in `simulator/`: a web page with an Echo Show–style frame, push-to-talk voice (browser speech-to-text + text-to-speech), and an MCP client whose "brain" is a **Strands agent on Amazon Bedrock** (this also satisfies the AWS Builder mini-challenge). Later it renders our MCP App UI.
   - Measure end-to-end latency per turn and record it.
   - No sign-in/OAuth (account linking is optional per Alexa+ docs; we store nothing and judges need no login).
   - Host the simulator + MCP server publicly with a rate limit: judges can't be expected to bring their own Bedrock access.
   - No real-Echo bridge: the user owns no Amazon device, and it would be voice-only.
4. After every stage: commit, push, and update the checkboxes in `docs/stages.md`.
5. **Adversarial review after every stage (standing rule).** Before starting the next stage, an independent reviewer (a fresh subagent with no stake in the code) tries to break the stage: wrong policy results, hidden engine defaults, single-source violations, circular tests, edge cases, security, over-engineering. Verify each finding, fix the real ones, record the outcome in `docs/stages.md`, commit. A stage is done only when it's built, tested, reviewed, and the fixes are committed.

## Accounts status (Sep 30, 2026)
- Devpost: registered; project "Unclaimed: A Benefits Screener for Alexa+" started (draft)
- Amazon Developer account: created (Sole Proprietorship). Useful for the optional real-Echo path (classic Alexa Skills Kit); Alexa+ add-on tools are not granted to hackathon participants.
- AWS: account created on the **Paid** plan ($200 credits). Region: **us-east-1**. Account 8109-9530-8352 holds $270 of credits (confirmed Oct 1). The `unclaimed-monthly-25` budget counts real spend (credits and refunds excluded) and emails at 50/80/100% and forecast 100%.
  - Never use root credentials or put keys in the repo. Access via IAM Identity Center (SSO) or an IAM admin user; CLI profile name: `unclaimed`. In WSL: install AWS CLI v2, then `aws configure sso --profile unclaimed` (or `aws configure --profile unclaimed`), and verify with `aws sts get-caller-identity --profile unclaimed`.
  - Before deploying, confirm the $25 budget alert exists (`aws budgets describe-budgets`) and that Bedrock model access is enabled in us-east-1.
- GitHub: public repo https://github.com/shiva-shivanibokka/unclaimed (personal account `shiva-shivanibokka`, which is the active `gh` account). This is a personal project: never use or switch to the `shivanibokka-confer` account.
- WSL Ubuntu 26.04 (WSL2): Node 24 via nvm (`source ~/.nvm/nvm.sh` in non-interactive shells, or the Windows npm leaks in via PATH), AWS CLI v2 at `~/.local/bin/aws`.

## Non-negotiables
- The AI phrases questions; **code does all arithmetic** and all eligibility decisions (PolicyEngine-US, pinned).
- **No database, and store nothing about the person.** The household draft travels inside each tool call.
- The engine silently defaults missing inputs (0/false; county = first in state; immigration = citizen). Always track known / unknown / declined.
- Units: ask in the person's units (paycheck + frequency, before/after taxes) and convert in code to the engine's periods (income yearly; SNAP/WIC monthly).
- States in scope: **CA + IL**. ZIP → county via the HUD crosswalk; ask the county only if a ZIP spans more than one.
- License: AGPL-3.0 (PolicyEngine-US is AGPL).
- **One source of truth per fact; nothing hard-coded.** Facts owned by others (rules, amounts, engine defaults, county names, ZIP data) are read from their source (PolicyEngine, HUD), never copied. Our own decisions (supported states, program list, thresholds) are defined once, with a name, and everything else imports or fetches them (other components use the engine's `/programs` and `/openapi.json`, never a re-typed copy). The one deliberate exception: test expectations are official figures typed in with citations, because a test that reads its answer from the engine can't catch the engine being wrong.

## Stack
- `mcp-server/`: TypeScript, MCP spec 2025-11-25, Streamable HTTP, remote URL, target < 500 ms per response. MCP Apps for Echo Show UI.
- **Demo path (decided Sep 30):** the user has no Amazon device and Alexa+ add-on tooling is allowlist-only (our AWS account is denied). Submission = self-hosted MCP server + a simulated Alexa+ web app (a Strands agent on Bedrock as the orchestrator, browser speech, Echo Show-style frame). Both are allowed by the track rules. The simulator must be public, free, and need no login for judges; rate-limit it. The add-on is a bonus only if Amazon grants access.
- `engine/`: Python 3.11+, FastAPI, `policyengine-us` (pinned in `engine/pyproject.toml` / `engine/uv.lock`, managed with uv, run in WSL). Always warm; measured numbers live only in `engine/README.md`. Reference scripts: `engine/research/`.
- Alexa+ tooling (`@alexa-ai/cli`, MCP Toolkit, Web Simulator) is **partner-only; not available to us**. We follow its published MCP requirements and demo through our own `simulator/`.
- AWS: hosting; Bedrock + Strands for eval tier C (AWS Builder mini-challenge requires Bedrock/AgentCore/Strands/Kiro/SageMaker).

## Question Engine (core IP)
After each answer: list candidates (dictionary `applies_when`/`requires`) → batched what-if runs (low vs high value) → score = (w·flips + Δ$) / cost → stop if no flip and < ~$25/mo, else ask the top question. No hard cap; after ~10 questions offer "estimate now or continue". Build it against a generic calculator interface (it will be reused for a mortgage document interview and published as a separate open-source library).

## Research scripts → tests (added Sep 30)
`engine/research/` holds the planning-session scripts (see its README). They are exploratory: they print, they don't assert. Turn their findings into automated tests, and add your own:
- **Engine-behavior guards** (new file, e.g. `engine/tests/test_engine_behavior.py`). These pin quirks our design depends on, so a PolicyEngine upgrade that changes them fails loudly:
  - Missing county silently becomes the first county in the state (CA → Alameda, IL → Adams); missing immigration status → citizen; missing numeric inputs → 0. Our layer must never send a household to the engine with these unset by accident.
  - Period units: income and rent inputs yearly; `snap`, `wic` monthly; `eitc`, `ctc`, `medicaid` yearly.
  - Input variables: the research scripts set `employment_income`, `rent`, `childcare_expenses`, which are calculated variables (setting them overrides the engine's formula). Tests use our engine's real inputs (`employment_income_before_lsr`, `pre_subsidy_rent`, `spm_unit_pre_subsidy_childcare_expenses`) via `unclaimed_engine`, never the scripts' `hh()`.
  - County changes results (ACA credit, single 55-year-old, $45K: LA ≠ Alameda ≠ Modoc), so the ZIP→county step is load-bearing.
  - Batching: `axes` variants return one result per variant, in order.
  These are behavior checks, not correctness checks. Keep them separate from `test_official.py`, whose expectations must stay official figures with citations (per the single-source rule).
- **Question Engine tests** (Stage 3), based on `followup_sensitivity.py`: for the CA/LA parent + kids 4 and 9 household, at $48K child care must rank above savings (it flips SNAP; savings changes nothing in CA), and job health insurance must matter at $48K but not at $32K. Assert rankings and flips, not exact dollar amounts.
- **Performance budget tests** (marked slow / optional in CI): warm single-household calc and a batched what-if round, compared against the 500 ms target; record the numbers in `docs/stages.md`.
- Keep `engine/research/` as-is for provenance; don't import it from production code.

## Working alongside the planning session
The user also runs a Claude (Cowork) planning chat that can read and write this folder. It edits only docs/CLAUDE.md, and only when asked. Before editing any doc, run `git status` and pull in or keep others' changes; never overwrite completed checkboxes in `docs/stages.md`.

## Git
- Commit messages end with the attribution lines in use in this repo's history.
- Log every friction with Amazon tools in `docs/friction-log.md` (up to 10% judging bonus).
