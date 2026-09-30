// Smoke test: connect with the official MCP client, list tools, call hello, report latency.
// Usage: npm run smoke -- [url]   (default http://localhost:8080/mcp)
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";

const url = new URL(process.argv[2] ?? "http://localhost:8080/mcp");

async function timed<T>(label: string, fn: () => Promise<T>): Promise<T> {
  const t = performance.now();
  const out = await fn();
  console.log(`${label.padEnd(18)} ${Math.round(performance.now() - t)} ms`);
  return out;
}

const client = new Client({ name: "unclaimed-smoke", version: "0.1.0" });
await timed("initialize", () => client.connect(new StreamableHTTPClientTransport(url)));
const { tools } = await timed("tools/list", () => client.listTools());
console.log("tools:", tools.map((t) => t.name).join(", "));
for (let i = 1; i <= 3; i++) {
  const res = await timed(`tools/call #${i}`, () =>
    client.callTool({ name: "hello", arguments: { name: "Sam" } }),
  );
  if (i === 1) console.log(JSON.stringify(res.structuredContent));
}
await client.close();
