// Unclaimed MCP server for Alexa+: Streamable HTTP (MCP 2025-11-25), stateless.
// A fresh server + transport per request, no sessions, nothing stored about the person:
// the household draft travels in the tool arguments and results (see tools.ts).
import express from "express";
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import { CallToolRequestSchema, ListToolsRequestSchema } from "@modelcontextprotocol/sdk/types.js";
import { AnswerError, buildTools, loadContext, type Tool } from "./tools.js";
import { UnitError } from "./units.js";
import { Ajv, type ValidateFunction } from "ajv";
import addFormats from "ajv-formats";
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
// Arguments are checked against each tool's schema before running: a model that sends
// text where a list belongs (or "18 * 30 * 52" for a number) gets told exactly what's wrong.
const validators = new Map<string, ValidateFunction>();
async function init(): Promise<void> {
  for (let attempt = 1; ; attempt++) {
    try {
      const built = buildTools(await loadContext());
      const ajv = new Ajv({ allErrors: true, strict: false });
      addFormats.default(ajv);
      for (const t of built) validators.set(t.name, ajv.compile(t.inputSchema));
      tools = built; // published only once every schema compiles
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
    const args = req.params.arguments ?? {};
    const validate = validators.get(tool.name)!;
    if (!validate(args)) {
      const problems = (validate.errors ?? []).slice(0, 5).map((e) => `${e.instancePath || "arguments"} ${e.message}`);
      return { isError: true, content: [{ type: "text", text: `Invalid arguments: ${problems.join("; ")}` }] };
    }
    try {
      const result = await tool.run(args);
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

// Public and without sign-in, so each client is limited (a screening is ~30-50 calls).
const REQUESTS_PER_IP_PER_MINUTE = Number(process.env.MCP_REQUESTS_PER_IP_PER_MINUTE ?? 300);
const windows = new Map<string, { start: number; count: number }>();
function rateLimit(req: express.Request, res: express.Response, next: express.NextFunction) {
  const now = Date.now();
  const ip = req.ip ?? "?";
  const w = windows.get(ip);
  if (!w || now - w.start >= 60_000) windows.set(ip, { start: now, count: 1 });
  else if (++w.count > REQUESTS_PER_IP_PER_MINUTE) {
    res.status(429).set("Retry-After", "60").json({ jsonrpc: "2.0", error: { code: -32000, message: "Too many requests" }, id: null });
    return;
  }
  if (windows.size > 10_000) for (const [k, v] of windows) if (now - v.start >= 60_000) windows.delete(k);
  next();
}

const app = express();
// Behind one load balancer (AWS): the client is the address it reports, not the balancer's.
app.set("trust proxy", Number(process.env.TRUSTED_PROXIES ?? 0)); // 1 in AWS (infra/deploy.sh)

app.use("/mcp", rateLimit);
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
