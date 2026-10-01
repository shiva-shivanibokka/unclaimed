import { test } from "node:test";
import assert from "node:assert/strict";
import { AnswerError, applyAnswers, noneForTheRest, reasons, type Context } from "../src/tools.js";

// A small dictionary shaped like the engine's. Ids are made up on purpose: the code must
// take them (and which question gives the hours for hourly pay) from the dictionary.
const q = (id: string, type: string, extra = {}) =>
  ({ id, entity: "person", definition: `${id}.`, ask: "", clarifiers: [], answer: { type, ...extra } }) as any;
const questions = [
  q("wages", "money", { person_units: ["hour", "month", "year"], hours_from: "hours" }),
  q("hours", "number"),
  q("is_disabled", "bool"),
];
const ctx = {
  dictionary: { questions, structure: { zip: {}, county: {}, people: {} } },
  questions: new Map(questions.map((x) => [x.id, x])),
} as unknown as Context;
const household = () => ({ state: "CA", people: [{ id: "me", relationship: "head", age: 32 }] });

test("hourly pay works when hours come in the same call, in any order and either id form", async () => {
  const h = household();
  const said = await applyAnswers(ctx, h, [
    { question: "me.wages", person: "me", value: 18, unit: "hour" },
    { question: "me.hours", value: 30 },
  ]);
  assert.equal((h.people[0] as any).wages, 18 * 30 * 52);
  // Read-backs line up with the answers as given (hours were applied first).
  assert.match(said[0], /^wages: \$18 an hour/);
  assert.equal(said[1], "hours: 30");
});

test("a person id with a dot still finds the question", async () => {
  const h = { state: "CA", people: [{ id: "kid.1", relationship: "child", age: 16 }] };
  await applyAnswers(ctx, h, [{ question: "kid.1.is_disabled", value: true }]);
  assert.equal((h.people[0] as any).is_disabled, true);
});

test("ZIP and county are household fields, never filled with 'none'", async () => {
  const h: any = household();
  await applyAnswers(ctx, h, [{ question: "county", value: "LAKE_COUNTY_IL" }]);
  assert.equal(h.county, "LAKE_COUNTY_IL");
  assert.deepEqual(noneForTheRest(ctx, [{ question: "county" }], new Set()), []);
});

test("an id naming a different person is refused", async () => {
  await assert.rejects(applyAnswers(ctx, household(), [{ question: "kid.is_disabled", person: "me", value: true }]), AnswerError);
});

test("'none of the rest' fills what wasn't answered or declined with zero / no", () => {
  const asked = [{ question: "wages", person: "me" }, { question: "is_disabled", person: "me" }, { question: "hours", person: "me" }];
  const filled = noneForTheRest(ctx, asked, new Set(["me.hours"]));
  assert.deepEqual(filled, [
    { question: "wages", person: "me", value: 0, unit: "year" },
    { question: "is_disabled", person: "me", value: false },
  ]);
});

test("why: the yes/no facts that came out yes, for the household or anyone in it", () => {
  const explain = [
    { label: "Meets the income test", value: true },
    { label: "Meets the asset test", value: false },
    { label: "Income limit", value: 50542 },
    { label: "Categorically eligible", by_person: { mom: false, kid: true } },
  ];
  assert.deepEqual(reasons(explain), ["Meets the income test", "Categorically eligible"]);
});
