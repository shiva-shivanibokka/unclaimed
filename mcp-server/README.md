# mcp-server

TypeScript MCP server for Alexa+ (Streamable HTTP, MCP spec 2025-11-25). Stateless: a fresh server per request, no sessions, nothing stored about the person. The household draft travels in every tool call and result.

## Tools

| Tool | Does |
|---|---|
| `start_screening` | ZIP + who lives there → the household draft and the first question (state from the engine's ZIP lookup; unsupported states are said so) |
| `answer` | Answers in the person's units (`1450` per `month`, `18` per `hour`, take-home pay) → converted to the engine's units, read back, next question (or `stop`). Declined questions go in `declined` |
| `get_results` | Programs, amounts, who is covered, and what's conditional on a declined answer; the assumption statements to say |
| `get_plan` | Stage 5 |

Single source: questions, phrasing, answer types, allowed units, options and the household JSON schema are read from the engine at startup (`/dictionary`, `/programs`, `/openapi.json`); ZIP data from `/zip/{zip}`; take-home → pay before taxes from `/gross_up` (PolicyEngine's tax rules). This server defines only calendar facts (weeks per year, …) in `src/units.ts`.

## Run locally

The engine must be running (see `engine/README.md`).

```bash
npm install
npm run build && ENGINE_URL=http://localhost:8000 npm start   # http://localhost:8080/mcp (health: /health, 503 until the engine is reachable)
npm test                        # unit tests (units, read-back)
npm run smoke                   # a full scripted screening through the MCP client, with timings
npm run smoke -- https://<deployed-host>/mcp
```

Config (environment): `ENGINE_URL`, `ENGINE_TIMEOUT_MS` (default 8000), `PORT` (8080), `MCP_ALLOWED_ORIGINS` (comma-separated browser origins allowed to call `/mcp`; requests with any other `Origin` get 403, as the MCP transport spec requires; requests without `Origin`, like Alexa+'s, are unaffected).

Responses are plain JSON (`enableJsonResponse`), not SSE; `GET`/`DELETE /mcp` return 405 because the server keeps no sessions. Logs carry the method and timing only, never answers.
