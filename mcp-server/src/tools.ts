// The screening tools. Stateless: the household draft travels in every call and result;
// nothing about the person is stored. Questions, phrasing, units, options and the
// household schema come from the engine at startup (single source); this layer only
// converts the person's units, reads answers back, and shapes results for a voice turn.

import { engine, EngineError, type Dictionary, type Json, type Question } from "./engine.js";
import { PER_YEAR, readBack, toYearly } from "./units.js";

/** A problem with what the model sent (bad unit, unknown person): it can ask again. */
export class AnswerError extends Error {}

export interface Tool {
  name: string;
  title: string;
  description: string;
  inputSchema: Json;
  run: (args: Json) => Promise<Json>;
}

export interface Context {
  dictionary: Dictionary;
  questions: Map<string, Question>;
  programNames: Map<string, string>;
  householdSchema: Json; // the engine's Household JSON schema; its refs point at `defs`
  defs: Json; // schema definitions, placed at the root of each tool's input schema
  personBase: Json; // the engine's Person schema: id, relationship, age
}

/** The engine's OpenAPI components, as a self-contained JSON schema rooted at `name`. */
function schemaFrom(openapi: Json, name: string): Json {
  const components: Json = openapi.components.schemas;
  const defs: Json = {};
  const visit = (node: any): any => {
    if (Array.isArray(node)) return node.map(visit);
    if (node && typeof node === "object") {
      if (typeof node.$ref === "string") {
        const ref = node.$ref.split("/").pop()!;
        if (!(ref in defs)) {
          defs[ref] = {};
          defs[ref] = visit(components[ref]);
        }
        return { $ref: `#/$defs/${ref}` };
      }
      return Object.fromEntries(Object.entries(node).map(([k, v]) => [k, visit(v)]));
    }
    return node;
  };
  const root = visit(components[name]);
  return { ...root, $defs: defs };
}

export async function loadContext(): Promise<Context> {
  const [dictionary, openapi, programs] = await Promise.all([
    engine.dictionary(),
    engine.openapi(),
    engine.programs(),
  ]);
  const { $defs: defs, ...household } = schemaFrom(openapi, "Household");
  const person: Json = defs.Person;
  return {
    dictionary,
    questions: new Map(dictionary.questions.map((q) => [q.id, q])),
    programNames: new Map(programs.map((p) => [p.id, p.name])),
    householdSchema: household,
    defs,
    personBase: {
      type: "object",
      required: ["id", "relationship", "age"],
      properties: { id: person.properties.id, relationship: person.properties.relationship, age: person.properties.age },
    },
  };
}

/** What the model needs to ask the next question (or to stop). */
function shapeNext(ctx: Context, next: Json): Json {
  if (next.stop) {
    return { stop: true, then: "Call get_results with the household.", conditional: next.conditional ?? {} };
  }
  const ask = next.ask;
  const mine = (next.top_candidates ?? []).find((c: Json) => c.question === ask.question && c.person === ask.person);
  const programs = [...new Set<string>((mine?.flips ?? []).map((f: string) => f.split(":")[0]))];
  const group = ask.group && next.together.length ? ctx.dictionary.groups[ask.group] : undefined;
  return {
    stop: false,
    ...(group && { ask_as_one_question: group.ask }),
    ask: { ...ask, could_change: programs.map((p) => ctx.programNames.get(p) ?? p) },
    ask_in_the_same_breath: next.together, // same shape as `ask`: phrasing, answer type, units, options
    questions_so_far: next.asked,
    offer_estimate: next.offer_estimate,
  };
}

function key(person: string | undefined, question: string) {
  return person ? `${person}.${question}` : question;
}

export interface Answer {
  question: string;
  person?: string;
  value: number | boolean | string;
  unit?: string;
  take_home?: boolean;
}

/** "None of the rest": every question just asked (`ask` and the same-breath ones) that this
 * call doesn't answer or decline is zero or no. Enums have no "none", so they must be answered. */
export function noneForTheRest(ctx: Context, asked: Json[], skip: Set<string>): Answer[] {
  return asked
    .filter((x) => !skip.has(key(x.person ?? undefined, x.question)))
    .map((x) => ({ x, q: ctx.questions.get(x.question)! }))
    .filter(({ q }) => q.answer.type !== "enum")
    .map(({ x, q }) => ({
      question: x.question,
      ...(x.person && { person: x.person }),
      value: q.answer.type === "bool" ? false : 0,
      ...(q.answer.type === "money" && { unit: q.answer.person_units?.at(-1) }),
    }));
}

/** Apply answers in the person's units to the household (engine units). Returns read-backs. */
export async function applyAnswers(ctx: Context, household: Json, answers: Answer[]): Promise<string[]> {
  const said: string[] = [];
  const people: Json[] = household.people;
  const target = (q: Question, a: Answer): Json => {
    if (q.entity === "household") return household;
    const p = people.find((x) => x.id === a.person);
    if (!p) throw new AnswerError(`${a.question} is asked per person: give person (one of ${people.map((x) => x.id).join(", ")})`);
    return p;
  };
  const grossUps: { owner: Json; q: Question; amount: number; unit: string; yearly: number; at: number }[] = [];
  // "person.question" (the form `declined` uses) is accepted for a person's answer too.
  for (const a of answers) {
    if (!a.question.includes(".")) continue;
    const [person, question] = a.question.split(".", 2) as [string, string];
    if (a.person && a.person !== person) throw new AnswerError(`${a.question} names ${person} but person is ${a.person}`);
    Object.assign(a, { person, question });
  }
  // Hours first: hourly pay needs them.
  const ordered = [...answers].sort((a, b) => Number(b.question === "weekly_hours_worked") - Number(a.question === "weekly_hours_worked"));
  for (const a of ordered) {
    if (a.question === "county" || a.question === "zip") {
      household[a.question] = String(a.value);
      said.push(`${a.question}: ${a.value}`);
      continue;
    }
    const q = ctx.questions.get(a.question);
    if (!q) throw new AnswerError(`unknown question "${a.question}": use the question id from next.ask (person goes in "person")`);
    const owner = target(q, a);
    const spec = q.answer;
    if (spec.type === "money") {
      if (typeof a.value !== "number") throw new AnswerError(`${a.question} needs a number of dollars`);
      const unit = a.unit ?? (spec.person_units?.length === 1 ? spec.person_units[0] : undefined);
      if (!unit) throw new AnswerError(`${a.question}: say per what (${spec.person_units!.join(", ")})`);
      if (a.take_home && spec.basis !== "before_tax") throw new AnswerError(`${a.question} isn't pay; take_home doesn't apply`);
      const yearly = toYearly(spec, a.value, unit, owner.weekly_hours_worked ?? undefined);
      if (a.take_home) {
        grossUps.push({ owner, q, amount: a.value, unit, yearly, at: said.length });
        said.push(""); // filled in once converted, below
      } else {
        owner[q.id] = yearly;
        said.push(readBack(q.definition.split(".")[0], a.value, unit, yearly));
      }
    } else if (spec.type === "enum") {
      if (!q.options?.includes(String(a.value))) throw new AnswerError(`${a.question} must be one of ${q.options?.join(", ")}`);
      owner[q.id] = a.value;
      said.push(`${q.id}: ${a.value}`);
    } else if (spec.type === "bool") {
      if (typeof a.value !== "boolean") throw new AnswerError(`${a.question} needs true or false`);
      owner[q.id] = a.value;
      said.push(`${q.id}: ${a.value ? "yes" : "no"}`);
    } else {
      if (typeof a.value !== "number") throw new AnswerError(`${a.question} needs a number`);
      owner[q.id] = a.value;
      said.push(`${q.id}: ${a.value}`);
    }
  }
  // Take-home pay -> pay before taxes, after every other answer is in (taxes depend on them).
  for (const g of grossUps) {
    const { gross } = await engine.grossUp(household, g.owner.id, g.q.id, g.yearly);
    g.owner[g.q.id] = gross;
    said[g.at] = readBack(g.q.definition.split(".")[0], g.amount, g.unit, gross, true);
  }
  return said;
}

export function buildTools(ctx: Context): Tool[] {
  const units = Object.keys(PER_YEAR).concat("hour");
  const answerItem = {
    type: "object",
    required: ["question", "value"],
    properties: {
      question: { type: "string", description: "Question id from `ask` (or ask_in_the_same_breath), e.g. rent" },
      person: { type: "string", description: "Person id, for questions asked per person" },
      value: { type: ["number", "boolean", "string"], description: "Dollars as a number, true/false, a number, or one of the options" },
      unit: { type: "string", enum: units, description: "For money: per what, as the person said it (hour, week, two_weeks, half_month, month, year; total for savings)" },
      take_home: { type: "boolean", description: "For pay: true if the amount is take-home (after taxes); it is converted to pay before taxes" },
    },
  };

  return [
    {
      name: "start_screening",
      title: "Start a benefits screening",
      description:
        "Start checking which benefits a household may qualify for (California and Illinois). Call after asking " +
        `for the ZIP code (${ctx.dictionary.structure.zip.ask}) and who lives there (${ctx.dictionary.structure.people.ask}). ` +
        "Returns the household draft (pass it unchanged to every later call) and the first question to ask. " +
        "Nothing about the person is stored.",
      inputSchema: {
        type: "object",
        required: ["zip", "people"],
        properties: {
          zip: { type: "string", pattern: "^\\d{5}$", description: ctx.dictionary.structure.zip.definition },
          people: {
            type: "array",
            minItems: 1,
            items: ctx.personBase,
            description: `${ctx.dictionary.structure.people.definition} Exactly one person has relationship "head" (the person speaking).`,
          },
        },
      },
      run: async ({ zip, people }) => {
        const { states } = await engine.zip(zip);
        const found = Object.keys(states);
        if (found.length === 0) {
          return { supported: false, say: "This ZIP code isn't in a state Unclaimed covers yet (California and Illinois)." };
        }
        // A ZIP in two supported states is rare; the engine's /next asks the county, which settles the state.
        const household = { state: found[0], zip, people };
        return { supported: true, household, next: shapeNext(ctx, await engine.next(household)) };
      },
    },
    {
      name: "answer",
      title: "Record answers and get the next question",
      description:
        "Record what the person said, in their own units (e.g. 1450 per month; 18 per hour; take-home pay), " +
        "and get the next question. Answer the asked question and any ask_in_the_same_breath ones together. " +
        "If the person doesn't want to answer, list the question in `declined` (that's fine: results will say what depends on it). " +
        "Read the `read_back` lines to the person so they can correct anything. When `next.stop` is true, call get_results.",
      inputSchema: {
        type: "object",
        required: ["household"],
        properties: {
          household: { ...ctx.householdSchema, description: "The household draft from the previous result, unchanged" },
          answers: { type: "array", items: answerItem },
          declined: {
            type: "array",
            items: { type: "string" },
            description: "Questions the person won't answer: 'question' or 'person.question'",
          },
          rest_none: {
            type: "boolean",
            description: "True when the person says none of the other things just asked apply (e.g. 'no other income'): they are recorded as zero / no",
          },
        },
        $defs: ctx.defs,
      },
      run: async ({ household, answers = [], declined = [], rest_none = false }) => {
        const h = structuredClone(household);
        const read_back = await applyAnswers(ctx, h, answers);
        if (rest_none) {
          // Stateless: what was just asked is the engine's next question for the household as
          // it was sent (served from the engine's cache). Filled-in "none"s aren't read back.
          const asked = await engine.next(household);
          const skip = new Set([...answers.map((a: Answer) => key(a.person, a.question)), ...declined]);
          if (!asked.stop) await applyAnswers(ctx, h, noneForTheRest(ctx, [asked.ask, ...asked.together], skip));
        }
        for (const d of declined as string[]) if (!h.declined?.includes(d)) h.declined = [...(h.declined ?? []), d];
        return { household: h, read_back, next: shapeNext(ctx, await engine.next(h)) };
      },
    },
    {
      name: "get_results",
      title: "Get benefit results",
      description:
        "Calculate which programs the household qualifies for and how much, once the questions stop (or when the person " +
        "wants an estimate now). Programs in `conditional_on` depend on an answer the person declined: say 'if ...', " +
        "never a flat 'you qualify'. Say the `we_assumed` statements briefly.",
      inputSchema: {
        type: "object",
        required: ["household"],
        properties: { household: { ...ctx.householdSchema, description: "The household draft, unchanged" } },
        $defs: ctx.defs,
      },
      run: async ({ household }) => {
        const r = await engine.calculate(household);
        const conditional: Json = r.conditional ?? {};
        return {
          as_of: r.as_of,
          county: r.county,
          programs: r.programs.map((p: Json) => ({
            id: p.id,
            name: p.name,
            eligible: p.eligible,
            ...(p.eligible_people && { eligible_people: p.eligible_people }),
            ...(p.amount !== undefined && { amount: p.amount, per: p.per }),
            ...(conditional[p.id] && { conditional_on: conditional[p.id] }),
          })),
          declined: r.assumptions.filter((a: Json) => a.status === "declined").map((a: Json) => key(a.person, a.question)),
          we_assumed: r.statements,
        };
      },
    },
  ];
}

export { EngineError };
