# Unclaimed: A Benefits Screener for Alexa+

A voice agent for Alexa+ that asks only the questions that change the answer, calculates benefits eligibility with an exact rules engine ([PolicyEngine-US](https://github.com/PolicyEngine/policyengine-us)), and hands the person a step-by-step plan to apply. California and Illinois: food, cash, health coverage, tax credits, phone, energy and child-care help.

Entry for the **Build, Ship, Shape: Amazon Developer Hackathon**, Alexa+ track (MCP server). Progress: [docs/stages.md](docs/stages.md).

**Try it:** [the live simulator](https://un-659b9ee0f93441afb26f3382e657e487.ecs.us-east-1.on.aws) (an Echo Show-style web page standing in for Alexa+; voice in Chrome or Edge, or type). No sign-in; nothing you say is stored. MCP endpoint: `https://un-c6b17643b34c4e5bae0eefe1f3457a23.ecs.us-east-1.on.aws/mcp`.

## How it works
- **The model talks; code decides.** The language model phrases questions and explains results. Which question comes next, when to stop, and what the household qualifies for are decided by code: the Question Engine runs what-ifs through PolicyEngine and asks the question whose answer could change the most (eligibility flips first, then dollars), and stops when no remaining answer would.
- **Nothing silently assumed.** Every answer is known, unknown or declined. The engine would quietly read a missing answer as 0/no; we never let it, and results that depend on an unknown say "if ...".
- **Nothing stored.** The household draft travels inside each tool call. No database, no sign-in.
- **A plan, not just a number.** For each program: how and where to apply, what to bring, what happens next, what trips people up, from the agencies' own pages (dated and cited), with a QR code that opens the application on the person's phone.

Architecture: [docs/architecture.md](docs/architecture.md). Evaluation: [docs/scorecard.md](docs/scorecard.md). Research write-up in progress: [docs/research-plan.md](docs/research-plan.md), [docs/research-results.md](docs/research-results.md).

## Run it locally
Needs Linux or macOS (on Windows, WSL2: PolicyEngine-US has paths longer than Windows allows), [uv](https://docs.astral.sh/uv/), Node 24+, and for the simulator only, AWS credentials with Amazon Bedrock access to the model in `simulator/simulator/defaults.env`. Three terminals, from the repo root:

```bash
# 1. The engine (PolicyEngine + Question Engine); ready when /health says "ready": true
cd engine && uv sync && uv run uvicorn unclaimed_engine.app:app --port 8000
```
```bash
# 2. The MCP server (what Alexa+ would call)
cd mcp-server && npm ci && npm run build && ENGINE_URL=http://localhost:8000 npm start
```
```bash
# 3. The Alexa+ simulator, then open http://localhost:8090
cd simulator && uv sync && AWS_REGION=us-east-1 MCP_URL=http://localhost:8080/mcp uv run uvicorn simulator.app:app --port 8090
```

Without Bedrock access, `cd mcp-server && npm run smoke` runs a whole screening through the MCP server with a scripted person. Tests: `cd engine && uv run pytest -m 'not slow'`, `cd mcp-server && npm test`, `cd simulator && uv run pytest`.

## Repo layout
| Folder | What's there |
|---|---|
| `engine/` | Python service: PolicyEngine-US wrapper, the Question Engine (`question_engine/`, a generic library), the benefits interview, ZIP → county |
| `dictionary/` | Every question we can ask and how each engine input is handled (the single source) |
| `plans/` | Plan cards per program and state, with sources and verification dates; ways to apply in `channels.yaml` |
| `mcp-server/` | TypeScript MCP server (Streamable HTTP, spec 2025-11-25) and the Echo Show screen (MCP Apps) |
| `simulator/` | The Alexa+ stand-in: web page + a Strands agent on Amazon Bedrock |
| `eval/` | Tiers A (handwritten), B (generated), C (simulated conversations), and the research experiments |
| `infra/` | AWS deployment (ECS Express Mode) |
| `docs/` | Architecture, stages, scorecard, friction log, research |

## Principles
- The AI phrases questions; code does all the arithmetic and every eligibility decision.
- Nothing about the person is stored.
- Every result is an estimate, with its assumptions stated; the agency decides. Not legal or financial advice.

## License
AGPL-3.0 (PolicyEngine-US is AGPL-3.0).
