// Unclaimed MCP server: Stage 0 "hello" build.
// Stateless Streamable HTTP: a fresh server + transport per request, no sessions,
// nothing stored about the person (the household draft will travel in tool args).
import express from "express";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import { z } from "zod";

const PORT = Number(process.env.PORT ?? 8080);
// Upper bound for the latency probe, so the knob can't be used to tie up the server.
const MAX_DELAY_MS = 10_000;

function buildServer(): McpServer {
  const server = new McpServer({ name: "unclaimed", version: "0.1.0" });

  server.registerTool(
    "hello",
    {
      title: "Say hello",
      description:
        "Greets the person and confirms the Unclaimed benefits screener is reachable. " +
        "Use when the person asks to test or say hello to Unclaimed.",
      inputSchema: {
        name: z.string().max(80).optional().describe("First name to greet, if the person gave one"),
        delay_ms: z
          .number()
          .int()
          .min(0)
          .max(MAX_DELAY_MS)
          .optional()
          .describe("Test only: wait this many milliseconds before answering (latency probe)"),
      },
    },
    async ({ name, delay_ms }) => {
      if (delay_ms) await new Promise((r) => setTimeout(r, delay_ms));
      const who = name ? `, ${name}` : "";
      const text =
        `Hello${who}! This is Unclaimed. I can check which benefits your household may be missing, ` +
        `like CalFresh, SNAP, WIC, or tax credits. Soon I'll ask a few short questions to find out.`;
      return {
        content: [{ type: "text", text }],
        structuredContent: { greeting: text, delayed_ms: delay_ms ?? 0 },
      };
    },
  );

  return server;
}

const app = express();
app.use(express.json({ limit: "256kb" }));

app.get("/health", (_req, res) => {
  res.json({ ok: true });
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

app.listen(PORT, () => {
  console.log(`unclaimed mcp-server listening on :${PORT}/mcp`);
});
