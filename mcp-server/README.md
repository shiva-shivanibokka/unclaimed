# mcp-server

TypeScript MCP server for Alexa+ (Streamable HTTP, MCP spec 2025-11-25).

Tools: `start_screening`, `answer`, `get_results`, `get_plan`. Stateless: the household draft travels in each tool call.

Built in Stage 0 (hello tool) and Stage 4 (full integration).

## Run locally

```bash
npm install
npm run build && npm start      # http://localhost:8080/mcp (health: /health)
npm run smoke                   # in another shell: initialize, tools/list, 3x hello, with timings
npm run smoke -- https://<deployed-host>/mcp
```

Stage 0 tool: `hello` (`name?`). Config (environment):
- `MCP_ALLOWED_ORIGINS`: comma-separated browser origins allowed to call `/mcp` (e.g. the simulator). Requests with any other `Origin` get 403, as the MCP transport spec requires; requests without `Origin` (server-to-server) are unaffected.
- `UNCLAIMED_LATENCY_PROBE=1`: adds a test-only `delay_ms` argument to `hello`, for measuring how a client handles slow responses. Off by default so the model never sees it.
Responses are plain JSON (`enableJsonResponse`), not SSE; `GET`/`DELETE /mcp` return 405 because the server keeps no sessions.
