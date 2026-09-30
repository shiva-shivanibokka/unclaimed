# Unclaimed: A Benefits Screener for Alexa+

A voice agent for Alexa+ that asks only the questions that change the answer, calculates benefits eligibility with an exact rules engine ([PolicyEngine-US](https://github.com/PolicyEngine/policyengine-us)), and hands the person a step-by-step action plan.

Entry for the **Build, Ship, Shape: Amazon Developer Hackathon**, Alexa+ track (MCP server). Deadline: Oct 23, 2026, 12:00 PM PDT.

**Status:** Stage 0 (setup and de-risk). See [docs/stages.md](docs/stages.md).

## How it works (short version)
1. **Frontend:** Alexa+ (voice) and the Echo Show screen (MCP App: result cards, checklist, QR handoff)
2. **Service:** a stateless TypeScript MCP server. It validates answers, converts units and reads answers back for confirmation.
3. **Engine side:** a Python service holding the **Question Engine** (chooses the next question by running what-ifs), PolicyEngine (the calculator), the dictionary of askable facts, the ZIP→county crosswalk and the action-plan catalog.
4. **Build and test:** a coverage checker, an eval harness (tiers A/B/C) and a scorecard, run on every change.

Full detail: [docs/architecture.md](docs/architecture.md)

## Principles
- The AI phrases questions; code does all the arithmetic.
- Nothing about the person is stored. There is no database.
- Every result is an estimate, with its assumptions stated. This is not legal or financial advice.

## Repo layout
| Folder | What goes there |
|---|---|
| `mcp-server/` | TypeScript MCP server (Streamable HTTP, MCP spec 2025-11-25) + MCP App UI |
| `engine/` | Python FastAPI service: Question Engine + PolicyEngine wrapper |
| `dictionary/` | YAML entries for every askable fact |
| `action-plans/` | YAML plan cards per program per state (CA, IL), with sources |
| `eval/` | Test households (tiers A/B/C), coverage checker, scorecard |
| `infra/` | AWS deployment |
| `docs/` | Architecture, stages, friction log |

## License
AGPL-3.0 (required because we build on PolicyEngine-US, which is AGPL-3.0).
