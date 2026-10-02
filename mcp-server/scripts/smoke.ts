// Smoke test: a full screening through the official MCP client, with a scripted person
// answering whatever is asked (in their own units), and the time of every call.
// Usage: npm run smoke -- [url] [pause seconds]   (default http://localhost:8080/mcp, no pause; the engine
// must be up). A pause before each answer stands in for the person talking, which is when
// the engine thinks ahead; with no pause every answer is the worst case.
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";

const url = new URL(process.argv[2] ?? "http://localhost:8080/mcp");
const pauseMs = Number(process.argv[3] ?? 0) * 1000;

// A Los Angeles mom of two: $18/hour for 30 hours, $1,450 rent, no other income.
const person: Record<string, { value: number | boolean | string; unit?: string }> = {
  weekly_hours_worked: { value: 30 },
  employment_income: { value: 18, unit: "hour" },
  housing_tenure: { value: "RENTER" },
  rent: { value: 1450, unit: "month" },
  childcare_expenses: { value: 400, unit: "month" },
};
const answerFor = (q: { question: string; answer: { type: string } }) =>
  person[q.question] ?? { value: q.answer.type === "bool" ? false : q.answer.type === "enum" ? "NONE" : 0 };

const ms: Record<string, number[]> = {};
async function call(name: string, args: Record<string, unknown>): Promise<any> {
  const t = performance.now();
  const res: any = await client.callTool({ name, arguments: args });
  (ms[name] ??= []).push(Math.round(performance.now() - t));
  if (res.isError) throw new Error(`${name}: ${res.content[0].text}`);
  return res.structuredContent;
}

const client = new Client({ name: "unclaimed-smoke", version: "0.2.0" });
await client.connect(new StreamableHTTPClientTransport(url));
console.log("tools:", (await client.listTools()).tools.map((t) => t.name).join(", "));

let r = await call("start_screening", {
  zip: "90011",
  people: [
    { id: "mom", relationship: "head", age: 32 },
    { id: "k1", relationship: "child", age: 4 },
    { id: "k2", relationship: "child", age: 9 },
  ],
});
let household = r.household;
let next = r.next;
while (!next.stop) {
  const asked = [next.ask, ...next.ask_in_the_same_breath];
  const answers = asked.map((q: any) => {
    const spec = q;
    const a = answerFor(q);
    // Enum defaults: the first option the engine offers.
    const value = a.value === "NONE" && spec.options ? spec.options[0] : a.value;
    return { question: q.question, ...(q.person && { person: q.person }), value, ...(typeof value === "number" && spec.answer?.type === "money" && { unit: a.unit ?? q.answer.person_units?.at(-1) ?? "year" }) };
  });
  console.log(`asks ${next.ask.question}${next.ask.person ? ` (${next.ask.person})` : ""} -> could change: ${next.ask.could_change.join(", ") || "-"}`);
  // Like a person who says "$18 an hour, about 30 hours": hourly pay comes with hours.
  for (const a of [...answers]) {
    if (a.unit === "hour") answers.push({ question: "weekly_hours_worked", person: a.person, value: person.weekly_hours_worked.value });
  }
  await new Promise((done) => setTimeout(done, pauseMs));
  r = await call("answer", { household, answers });
  household = r.household;
  next = r.next;
  for (const line of r.read_back) if (!line.endsWith(": no") && !line.includes(": $0")) console.log("   read back:", line);
}
await new Promise((done) => setTimeout(done, pauseMs));
const results = await call("get_results", { household });
const eligible = results.programs.filter((p: any) => p.eligible);
for (const p of eligible) console.log(`  ${p.name}: ${p.amount ?? "covered"} ${p.per ?? ""}  why: ${p.why?.join("; ") ?? "-"}${p.if_also ? `  if: ${p.if_also.join(" ")}` : ""}`);
console.log("  also check:", results.also_check.map((p: any) => p.name).join(", ") || "-");
const { plans } = await call("get_plan", { household, programs: [...eligible, ...results.also_check].map((p: any) => p.id) });
for (const p of plans) console.log(`  plan: ${Object.values(p.names).join(" and ")} -> ${p.apply[0].where}`);
for (const [name, xs] of Object.entries(ms)) {
  const sorted = [...xs].sort((a, b) => a - b);
  console.log(`${name.padEnd(16)} n=${xs.length} median ${sorted[Math.floor(sorted.length / 2)]} ms, max ${sorted.at(-1)} ms`);
}
await client.close();
