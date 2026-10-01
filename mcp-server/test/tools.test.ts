import { test } from "node:test";
import assert from "node:assert/strict";
import { AnswerError, applyAnswers, noneForTheRest, type Context } from "../src/tools.js";

// A two-question dictionary, shaped like the engine's.
const q = (id: string, type: string, extra = {}) =>
  ({ id, entity: "person", definition: `${id}.`, ask: "", clarifiers: [], answer: { type, ...extra } }) as any;
const questions = [
  q("employment_income", "money", { person_units: ["hour", "month", "year"] }),
  q("weekly_hours_worked", "number"),
  q("is_disabled", "bool"),
];
const ctx = { questions: new Map(questions.map((x) => [x.id, x])) } as unknown as Context;
const household = () => ({ state: "CA", people: [{ id: "me", relationship: "head", age: 32 }] });

test("hourly pay works when hours come in the same call, in any order and either id form", async () => {
  const h = household();
  await applyAnswers(ctx, h, [
    { question: "me.employment_income", person: "me", value: 18, unit: "hour" },
    { question: "me.weekly_hours_worked", value: 30 },
  ]);
  assert.equal((h.people[0] as any).employment_income, 18 * 30 * 52);
});

test("an id naming a different person is refused", async () => {
  await assert.rejects(applyAnswers(ctx, household(), [{ question: "kid.is_disabled", person: "me", value: true }]), AnswerError);
});

test("'none of the rest' fills what wasn't answered or declined with zero / no", () => {
  const asked = [{ question: "employment_income", person: "me" }, { question: "is_disabled", person: "me" }, { question: "weekly_hours_worked", person: "me" }];
  const filled = noneForTheRest(ctx, asked, new Set(["me.weekly_hours_worked"]));
  assert.deepEqual(filled, [
    { question: "employment_income", person: "me", value: 0, unit: "year" },
    { question: "is_disabled", person: "me", value: false },
  ]);
});
