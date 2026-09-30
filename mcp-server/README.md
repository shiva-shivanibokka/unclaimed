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

Stage 0 tool: `hello` (`name?`, `delay_ms?`). `delay_ms` is a test-only knob to find out how Alexa+ enforces the 500 ms limit.
Responses are plain JSON (`enableJsonResponse`), not SSE; `GET`/`DELETE /mcp` return 405 because the server keeps no sessions.
