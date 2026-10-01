// Client for the Unclaimed engine (engine/), the single source for questions, programs,
// the household schema, ZIP data and every calculation. Nothing here is a copy of it.

export const ENGINE_URL = (process.env.ENGINE_URL ?? "http://localhost:8000").replace(/\/$/, "");
// A voice turn can't wait longer than this for the engine; past it, the tool says "busy".
const TIMEOUT_MS = Number(process.env.ENGINE_TIMEOUT_MS ?? 8000);

export type Json = Record<string, any>;

export interface AnswerSpec {
  type: "money" | "bool" | "number" | "enum";
  unit?: string;
  person_units?: string[];
  basis?: string;
  min?: number;
  max?: number;
  negative?: boolean;
}

export interface Question {
  id: string;
  entity: "person" | "household";
  definition: string;
  ask: string;
  answer: AnswerSpec;
  options?: string[];
  clarifiers: string[];
}

export interface Dictionary {
  questions: Question[];
  statements: string[];
  structure: Record<string, { definition: string; ask: string }>;
  groups: Record<string, { ask: string }>;
}

/** An error the person (via the model) can act on, e.g. "busy, try again" or a bad answer. */
export class EngineError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

async function call(path: string, body?: unknown): Promise<Json> {
  const res = await fetch(`${ENGINE_URL}${path}`, {
    method: body === undefined ? "GET" : "POST",
    headers: body === undefined ? undefined : { "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal: AbortSignal.timeout(TIMEOUT_MS),
  }).catch((e) => {
    throw new EngineError(e?.name === "TimeoutError" ? "The calculator took too long; try again." : "The calculator is unreachable.", 503);
  });
  const data = (await res.json().catch(() => ({}))) as Json;
  if (!res.ok) {
    const detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail ?? data);
    throw new EngineError(res.status === 503 ? "The calculator is busy; try again in a moment." : detail, res.status);
  }
  return data;
}

export const engine = {
  dictionary: () => call("/dictionary") as Promise<Dictionary>,
  openapi: () => call("/openapi.json"),
  programs: () => call("/programs") as unknown as Promise<Json[]>,
  zip: (zip: string) => call(`/zip/${encodeURIComponent(zip)}`),
  next: (household: Json) => call("/next", household),
  calculate: (household: Json) => call("/calculate", household),
  grossUp: (household: Json, person: string, question: string, takeHome: number) =>
    call("/gross_up", { household, person, question, take_home: takeHome }),
};
