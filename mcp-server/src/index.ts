// Unclaimed MCP server for Alexa+: Streamable HTTP (MCP 2025-11-25), stateless.
// A fresh server + transport per request, no sessions, nothing stored about the person:
// the household draft travels in the tool arguments and results (see tools.ts).
import express from "express";
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import { CallToolRequestSchema, ListToolsRequestSchema } from "@modelcontextprotocol/sdk/types.js";
import { AnswerError, buildTools, loadContext, type Tool } from "./tools.js";
import { UnitError } from "./units.js";
import { EngineError } from "./engine.js";

const PORT = Number(process.env.PORT ?? 8080);
// Browser origins allowed to call /mcp (comma-separated), e.g. the simulator's URL.
// Requests without an Origin header (server-to-server, like Alexa+) are unaffected.
// The MCP transport spec (2025-11-25) requires rejecting an invalid Origin.
const ALLOWED_ORIGINS = new Set(
  (process.env.MCP_ALLOWED_ORIGINS ?? "").split(",").map((o) => o.trim()).filter(Boolean),
);

// Tools are built once from the engine's dictionary and schema (retried until the engine is up).
let tools: Tool[] = [];
async function init(): Promise<void> {
  for (let attempt = 1; ; attempt++) {
    try {
      tools = buildTools(await loadContext());
      console.log(JSON.stringify({ ready: true, tools: tools.map((t) => t.name) }));
      return;
    } catch (e) {
      console.error(JSON.stringify({ waiting_for_engine: attempt, error: String(e) }));
      await new Promise((r) => setTimeout(r, Math.min(30_000, 1000 * attempt)));
    }
  }
}

function buildServer(): Server {
  const server = new Server({ name: "unclaimed", version: "0.2.0" }, { capabilities: { tools: {} } });
  server.setRequestHandler(ListToolsRequestSchema, async () => ({
    tools: tools.map(({ name, title, description, inputSchema }) => ({ name, title, description, inputSchema })),
  }));
  server.setRequestHandler(CallToolRequestSchema, async (req) => {
    const tool = tools.find((t) => t.name === req.params.name);
    if (!tool) return { isError: true, content: [{ type: "text", text: `Unknown tool ${req.params.name}` }] };
    try {
      const result = await tool.run(req.params.arguments ?? {});
      return { content: [{ type: "text", text: JSON.stringify(result) }], structuredContent: result };
    } catch (e) {
      // Answers the model can fix (bad unit, unknown person) or a busy engine: tell the model, not a crash.
      const message = e instanceof Error ? e.message : String(e);
      const expected = e instanceof AnswerError || e instanceof UnitError || (e instanceof EngineError && e.status < 500);
      // Log the kind only: messages can echo the person's answers.
      if (!expected) console.error(JSON.stringify({ tool: tool.name, error: e instanceof Error ? e.name : "unknown" }));
      return { isError: true, content: [{ type: "text", text: message }] };
    }
  });
  return server;
}

const app = express();

app.use("/mcp", (req, res, next) => {
  const origin = req.headers.origin;
  if (origin && !ALLOWED_ORIGINS.has(origin)) {
    res.status(403).json({ jsonrpc: "2.0", error: { code: -32000, message: "Origin not allowed" }, id: null });
    return;
  }
  next();
});
app.use(express.json({ limit: "256kb" }));

app.get("/health", (_req, res) => {
  res.status(tools.length ? 200 : 503).json({ ok: tools.length > 0 });
});

app.post("/mcp", async (req, res) => {
  const started = performance.now();
  const server = buildServer();
  const transport = new StreamableHTTPServerTransport({
    sessionIdGenerator: undefined, // stateless
    enableJsonResponse: true, // plain JSON, no SSE stream: lower latency for Alexa+
  });
  res.on("close", () => {
    transport.close();
    server.close();
  });
  try {
    await server.connect(transport);
    await transport.handleRequest(req, res, req.body);
  } catch (err) {
    console.error("mcp error", err);
    if (!res.headersSent) {
      res.status(500).json({
        jsonrpc: "2.0",
        error: { code: -32603, message: "Internal server error" },
        id: null,
      });
    }
  } finally {
    const method = typeof req.body?.method === "string" ? req.body.method : "batch";
    console.log(JSON.stringify({ method, ms: Math.round(performance.now() - started) }));
  }
});

// Stateless server: no SSE stream to open and no session to delete.
const methodNotAllowed = (_req: express.Request, res: express.Response) => {
  res.status(405).set("Allow", "POST").json({
    jsonrpc: "2.0",
    error: { code: -32000, message: "Method not allowed" },
    id: null,
  });
};
app.get("/mcp", methodNotAllowed);
app.delete("/mcp", methodNotAllowed);

// Malformed JSON: answer as JSON-RPC (parse error), not Express's HTML error page.
app.use((err: unknown, _req: express.Request, res: express.Response, next: express.NextFunction) => {
  if (err instanceof SyntaxError) {
    res.status(400).json({ jsonrpc: "2.0", error: { code: -32700, message: "Parse error" }, id: null });
    return;
  }
  next(err);
});

app.listen(PORT, () => {
  console.log(`unclaimed mcp-server listening on :${PORT}/mcp`);
  void init();
});
