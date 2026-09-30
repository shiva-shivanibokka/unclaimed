# CLAUDE.md: context for coding agents

**Project:** Unclaimed, an Alexa+ benefits screener. Entry for the Amazon Developer Hackathon "Build, Ship, Shape", **Alexa+ track** + AWS Builder and Open Source mini-challenges.
**Deadline:** Oct 23, 2026, 12:00 PM PDT (target submit: evening of Oct 22).
**Read first:** `docs/architecture.md`, `docs/stages.md`. Devpost story draft: `docs/devpost-story.md`.

## Non-negotiables
- The AI phrases questions; **code does all arithmetic** and all eligibility decisions (PolicyEngine-US, pinned).
- **No database, and store nothing about the person.** The household draft travels inside each tool call.
- The engine silently defaults missing inputs (0/false; county = first in state; immigration = citizen). Always track known / unknown / declined.
- Units: ask in the person's units (paycheck + frequency, before/after taxes) and convert in code to the engine's periods (income yearly; SNAP/WIC monthly).
- States in scope: **CA + IL**. ZIP → county via the HUD crosswalk; ask the county only if a ZIP spans more than one.
- License: AGPL-3.0 (PolicyEngine-US is AGPL).

## Stack
- `mcp-server/`: TypeScript, MCP spec 2025-11-25, Streamable HTTP, remote URL, target < 500 ms per response. MCP Apps for Echo Show UI.
- `engine/`: Python 3.11+, FastAPI, `policyengine-us`. Always warm (cold start ~14 s + ~5 s first calc per program; ~1 GB RAM).
- Alexa+ tooling: `@alexa-ai/cli` (Node 24+, macOS/Ubuntu → use WSL2 Ubuntu on this Windows machine). `alexa-ai configure`, `alexa-ai new mcp`, `alexa-ai deploy`, `alexa-ai submit`.
- AWS: hosting; Bedrock + Strands for eval tier C (AWS Builder mini-challenge requires Bedrock/AgentCore/Strands/Kiro/SageMaker).

## Question Engine (core IP)
After each answer: list candidates (dictionary `applies_when`/`requires`) → batched what-if runs (low vs high value) → score = (w·flips + Δ$) / cost → stop if no flip and < ~$25/mo, else ask the top question. No hard cap; after ~10 questions offer "estimate now or continue". Build it against a generic calculator interface (it will be reused for a mortgage document interview and published as a separate open-source library).

## Git
- Commit messages end with the attribution lines in use in this repo's history.
- Log every friction with Amazon tools in `docs/friction-log.md` (up to 10% judging bonus).
