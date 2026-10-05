// The screening tools. Stateless: the household draft travels in every call and result;
// nothing about the person is stored. Questions, phrasing, units, options and the
// household schema come from the engine at startup (single source); this layer only
// converts the person's units, reads answers back, and shapes results for a voice turn.

import { engine, EngineError, type Dictionary, type Json, type Question } from "./engine.js";
import { readBack, toYearly } from "./units.js";
import { SCREEN_URI } from "./screen.js";

/** A problem with what the model sent (bad unit, unknown person): it can ask again. */
export class AnswerError extends Error {}

export interface Tool {
  name: string;
  title: string;
  description: string;
  inputSchema: Json;
  _meta?: Json; // e.g. the screen that shows the result (MCP Apps)
  run: (args: Json) => Promise<Json>;
}

export interface Context {
  dictionary: Dictionary;
  questions: Map<string, Question>;
  programNames: Map<string, string>;
  states: string[]; // the states the engine's programs cover
  plans: Record<string, Record<string, Json>>; // state -> card id -> plan card (engine /plans)
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
  const states = [...new Set(programs.flatMap((p) => p.states as string[]))].sort();
  const plans = Object.fromEntries(await Promise.all(states.map(async (s) => [s, await engine.plans(s)] as const)));
  return {
    dictionary,
    questions: new Map(dictionary.questions.map((q) => [q.id, q])),
    programNames: new Map(programs.map((p) => [p.id, p.name])),
    states,
    plans,
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
  const programs: string[] = next.could_change ?? [];
  const group = ask.group && next.together.length ? ctx.dictionary.groups[ask.group] : undefined;
  return {
    stop: false,
    ...(group && { ask_as_one_question: group.ask }),
    ask: { ...ask, could_change: programs.map((p) => ctx.programNames.get(p) ?? p) },
    ask_in_the_same_breath: next.together, // same shape as `ask`: phrasing, answer type, units, options
    questions_so_far: next.asked,
  };
}

/** ZIP or county: asked like a question, but a field of the household (dictionary `structure`). */
function isLocation(ctx: Context, question: string) {
  return question in ctx.dictionary.structure && question !== "people";
}

/** The plan card for each program in a state: program id -> card. */
export function cardsByProgram(ctx: Context, state: string): Map<string, Json> {
  return new Map(Object.values(ctx.plans[state] ?? {}).flatMap((c) => (c.programs as string[]).map((p) => [p, c] as const)));
}

/** What the person is told: "likely" (eligible, nothing open), "maybe" (eligible only "if ...",
 * or not yet but an answer we don't have could change that), or "no". */
export function status(p: Json, conditionalOn?: string[], ifAlso?: string[]): "likely" | "maybe" | "no" {
  if (p.eligible) return conditionalOn || ifAlso ? "maybe" : "likely";
  return conditionalOn ? "maybe" : "no";
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
    .filter((x) => !skip.has(key(x.person ?? undefined, x.question)) && !isLocation(ctx, x.question))
    .map((x) => ({ x, q: ctx.questions.get(x.question)! }))
    .filter(({ q }) => q.answer.type !== "enum")
    .map(({ x, q }) => ({
      question: x.question,
      ...(x.person && { person: x.person }),
      value: q.answer.type === "bool" ? false : 0,
    }));
}

/** Apply answers in the person's units to the household (engine units). Returns the
 * read-backs, one per answer, in the order given. */
export async function applyAnswers(ctx: Context, household: Json, answers: Answer[]): Promise<string[]> {
  const said: string[] = answers.map(() => "");
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
    const dot = a.question.lastIndexOf(".");
    const [person, question] = [a.question.slice(0, dot), a.question.slice(dot + 1)];
    if (a.person && a.person !== person) throw new AnswerError(`${a.question} names ${person} but person is ${a.person}`);
    Object.assign(a, { person, question });
  }
  // Hours first: hourly pay needs them (the dictionary says which question gives them).
  const hours = new Set(ctx.dictionary.questions.map((q) => q.answer.hours_from).filter(Boolean));
  const ordered = [...answers].sort((a, b) => Number(hours.has(b.question)) - Number(hours.has(a.question)));
  for (const a of ordered) {
    const at = answers.indexOf(a);
    if (isLocation(ctx, a.question)) {
      household[a.question] = String(a.value);
      said[at] = `${a.question}: ${a.value}`;
      continue;
    }
    const q = ctx.questions.get(a.question);
    if (!q) throw new AnswerError(`unknown question "${a.question}": use the question id from next.ask (person goes in "person")`);
    const owner = target(q, a);
    const spec = q.answer;
    if (spec.type === "money") {
      if (typeof a.value !== "number") throw new AnswerError(`${a.question} needs a number of dollars`);
      if (a.value === 0) { // $0 is $0 per anything: "none" needs no unit
        owner[q.id] = 0;
        said[at] = `${q.definition.split(".")[0]}: none`;
        continue;
      }
      const unit = a.unit ?? (spec.person_units?.length === 1 ? spec.person_units[0] : undefined);
      if (!unit) throw new AnswerError(`${a.question}: say per what (${spec.person_units!.join(", ")})`);
      if (a.take_home && spec.basis !== "before_tax") throw new AnswerError(`${a.question} isn't pay; take_home doesn't apply`);
      const yearly = toYearly(spec, a.value, unit, spec.hours_from ? owner[spec.hours_from] ?? undefined : undefined);
      if (a.take_home) {
        owner[q.id] = yearly; // a first guess, so a partner's conversion doesn't see $0
        grossUps.push({ owner, q, amount: a.value, unit, yearly, at }); // read back once converted, below
      } else {
        owner[q.id] = yearly;
        said[at] = readBack(q.definition.split(".")[0], a.value, unit, yearly);
      }
    } else if (spec.type === "enum") {
      if (!q.options?.includes(String(a.value))) throw new AnswerError(`${a.question} must be one of ${q.options?.join(", ")}`);
      owner[q.id] = a.value;
      said[at] = `${q.id}: ${a.value}`;
    } else if (spec.type === "bool") {
      if (typeof a.value !== "boolean") throw new AnswerError(`${a.question} needs true or false`);
      owner[q.id] = a.value;
      said[at] = `${q.id}: ${a.value ? "yes" : "no"}`;
    } else {
      if (typeof a.value !== "number") throw new AnswerError(`${a.question} needs a number`);
      owner[q.id] = a.value;
      said[at] = `${q.id}: ${a.value}`;
    }
  }
  // Take-home pay -> pay before taxes, after every other answer is in (taxes depend on them).
  // Partners are taxed jointly, so with two take-home answers each conversion runs again
  // once the other's pay before taxes is known.
  for (let pass = 0; pass < Math.min(grossUps.length, 2); pass++) {
    for (const g of grossUps) {
      g.owner[g.q.id] = (await engine.grossUp(household, g.owner.id, g.q.id, g.yearly)).gross;
    }
  }
  for (const g of grossUps) said[g.at] = readBack(g.q.definition.split(".")[0], g.amount, g.unit, g.owner[g.q.id], true);
  return said;
}

export function buildTools(ctx: Context): Tool[] {
  const units = [...new Set(ctx.dictionary.questions.flatMap((q) => q.answer.person_units ?? []))];
  const states = ctx.states.join(" and ");
  const answerItem = {
    type: "object",
    required: ["question", "value"],
    properties: {
      question: { type: "string", description: "Question id from `ask` (or ask_in_the_same_breath), e.g. rent" },
      person: { type: "string", description: "Person id, for questions asked per person" },
      value: { type: ["number", "boolean", "string"], description: "Dollars as a number, true/false, a number, or one of the options" },
      unit: { type: "string", enum: units, description: `For money: per what, as the person said it (${units.join(", ")}); not needed for 0` },
      take_home: { type: "boolean", description: "For pay: true if the amount is take-home (after taxes); it is converted to pay before taxes" },
    },
  };

  return [
    {
      name: "start_screening",
      title: "Start a benefits screening",
      description:
        `Start checking which benefits a household may qualify for (states covered: ${states}). Call after asking ` +
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
          return { supported: false, say: `This ZIP code isn't in a state Unclaimed covers yet (it covers ${states}).` };
        }
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
        "If the person doesn't want to answer, list the question in `declined` (that's fine: results will say what depends on it); " +
        "if they answer it later after all, just answer it. " +
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
          // it was sent (served from the engine's cache). A filled-in "no" can be a claim the person didn't make (heat not included in the
          // rent), so those are read back to be corrected; filled-in zeros aren't (too many to say).
          const asked = await engine.next(household);
          const skip = new Set([...answers.map((a: Answer) => key(a.person, a.question)), ...declined]);
          if (!asked.stop) {
            const fills = noneForTheRest(ctx, [asked.ask, ...asked.together], skip);
            const said = await applyAnswers(ctx, h, fills);
            read_back.push(...said.filter((_, i) => typeof fills[i].value === "boolean"));
          }
        }
        // An answer replaces an earlier "I'd rather not say".
        const answered = new Set(answers.map((a: Answer) => key(a.person, a.question)));
        h.declined = [...new Set([...(h.declined ?? []), ...(declined as string[])])].filter((d) => !answered.has(d));
        return { household: h, read_back, next: shapeNext(ctx, await engine.next(h)) };
      },
    },
    {
      name: "check_programs",
      title: "Check programs that came out as maybe",
      description:
        "When the person wants to know about programs get_results showed as maybe (`conditional_on`, or not eligible " +
        "yet), or asks to check them all: returns the household with those programs in focus and the first question " +
        "that could settle them. Ask it and record the answers with `answer` as usual; when `next.stop` is true, call " +
        "get_results again, so the screen updates (a program that turns out not to fit leaves the list).",
      inputSchema: {
        type: "object",
        required: ["household", "programs"],
        properties: {
          household: { ...ctx.householdSchema, description: "The household draft, unchanged" },
          programs: {
            type: "array",
            minItems: 1,
            items: { type: "string", enum: [...ctx.programNames.keys()] },
            description: "Program ids from get_results",
          },
        },
        $defs: ctx.defs,
      },
      run: async ({ household, programs }) => {
        const h = { ...structuredClone(household), focus: [...new Set(programs as string[])] };
        const next = await engine.next(h);
        // Nothing left to ask: what still decides these is an answer the person declined.
        const declined = [...new Set((programs as string[]).flatMap((p) => next.conditional?.[p] ?? []))];
        return {
          household: h,
          next: shapeNext(ctx, next),
          ...(next.stop && declined.length && {
            declined_answers: declined,
            then: "These depend on answers the person chose not to give. Ask whether they'd like to answer them now " +
              "(that's optional; an answer replaces the decline), then call get_results.",
          }),
        };
      },
    },
    {
      name: "get_results",
      title: "Get benefit results",
      _meta: { ui: { resourceUri: SCREEN_URI } },
      description:
        "Calculate which programs the household qualifies for and how much, once the questions stop (or when the person " +
        "wants an estimate now). Each program's `status` is what to tell the person: say 'you likely qualify' only for " +
        "\"likely\"; a \"maybe\" is always said with 'if' or 'might'; \"no\" programs aren't mentioned unless asked. " +
        "Programs with `conditional_on` depend on an answer the person declined or wasn't asked yet " +
        "(check_programs asks what settles them): " +
        "say 'if ...', never a flat 'you qualify'; so do programs with `if_also` (a condition the calculator can't " +
        "check, like which utility serves the home): say it as 'if ...'. `why` lists the tests the household meets, in " +
        "the calculator's words: say them plainly. The screen lists the `we_assumed` statements (say them if asked). If `ready` is false, ask `next.ask` first: " +
        "no estimate is possible without it. Then offer the plan (get_plan) for the programs they want to apply for.",
      inputSchema: {
        type: "object",
        required: ["household"],
        properties: { household: { ...ctx.householdSchema, description: "The household draft, unchanged" } },
        $defs: ctx.defs,
      },
      run: async ({ household }) => {
        const cards = cardsByProgram(ctx, household.state);
        // Before the questions run out, an unasked answer is read by the engine as 0/no: the
        // essentials (location, pay) must be in, and what's still open makes results conditional.
        const next = await engine.next(household);
        if (!next.stop && next.core) return { ready: false, next: shapeNext(ctx, next) };
        const r = await engine.calculate(household);
        const conditional: Json = r.conditional ?? {};
        for (const [program, keys] of Object.entries<string[]>(next.unanswered ?? {})) {
          conditional[program] = [...new Set([...(conditional[program] ?? []), ...keys])];
        }
        const programs = r.programs.map((p: Json) => ({
            id: p.id,
            name: p.name,
            status: status(p, conditional[p.id], cards.get(p.id)?.not_calculated),
            eligible: p.eligible,
            ...(p.eligible_people && { eligible_people: p.eligible_people }),
            ...(p.amount !== undefined && { amount: p.amount, per: p.per }),
            ...(conditional[p.id] && { conditional_on: conditional[p.id] }),
            ...(p.eligible && { why: p.why }),
            ...(p.eligible && cards.get(p.id)?.not_calculated && { if_also: cards.get(p.id)!.not_calculated }),
          }));
        // Health coverage has no amount (its engine value is the cost of coverage): listed after cash.
        const value = new Map<string, number>(r.programs.map((p: Json) => [p.id, p.amount === undefined ? 0 : p.monthly_value]));
        return {
          ready: true,
          as_of: r.as_of,
          county: r.county,
          // What to say first: likely programs biggest first (by value a month), maybes by name only.
          summary: {
            likely: programs.filter((p: Json) => p.status === "likely")
              .sort((a: Json, b: Json) => value.get(b.id)! - value.get(a.id)!).map((p: Json) => p.name),
            maybe: programs.filter((p: Json) => p.status === "maybe").map((p: Json) => p.name),
          },
          programs,
          declined: r.assumptions.filter((a: Json) => a.status === "declined").map((a: Json) => key(a.person, a.question)),
          we_assumed: r.statements,
          // Programs with a plan card that the calculator doesn't model: worth a look, no verdict.
          also_check: [...cards].filter(([p]) => !ctx.programNames.has(p))
            .map(([id, card]) => ({ id, name: card.names[id], what: card.what })),
        };
      },
    },
    {
      name: "get_plan",
      title: "Get the plan to apply",
      _meta: { ui: { resourceUri: SCREEN_URI } },
      description:
        "What to do next for the programs the person wants to apply for: how and where to apply, what to bring, what " +
        "happens after, and what to watch out for, from the agencies' own pages. Say the first way to apply and offer " +
        "what to bring; the screen shows the full list with a code that opens the application on their phone.",
      inputSchema: {
        type: "object",
        required: ["household", "programs"],
        properties: {
          household: { ...ctx.householdSchema, description: "The household draft, unchanged" },
          programs: {
            type: "array",
            minItems: 1,
            items: { type: "string" },
            description: "Program ids from get_results (programs and also_check)",
          },
        },
        $defs: ctx.defs,
      },
      run: async ({ household, programs }) => {
        const cards = cardsByProgram(ctx, household.state);
        const missing = (programs as string[]).filter((p) => !cards.has(p));
        if (missing.length) throw new AnswerError(`no plan for ${missing.join(", ")} here: use ids from get_results`);
        // Programs applied for together share one plan, named for the ones asked about.
        const plans = [...new Set((programs as string[]).map((p) => cards.get(p)!))];
        return {
          plans: plans.map(({ state: _, names, ...card }) => ({
            ...card,
            names: Object.fromEntries(Object.entries<string>(names).filter(([p]) => (programs as string[]).includes(p))),
          })),
        };
      },
    },
  ];
}

export { EngineError };
