import { test } from "node:test";
import assert from "node:assert/strict";
import { readBack, toYearly, UnitError } from "../src/units.js";

const pay = { type: "money" as const, person_units: ["hour", "week", "two_weeks", "half_month", "month", "year"], hours_from: "hours" };

test("pay in the person's units becomes dollars per year", () => {
  assert.equal(toYearly(pay, 1450, "month"), 17_400);
  assert.equal(toYearly(pay, 1000, "two_weeks"), 26_000);
  assert.equal(toYearly(pay, 1000, "half_month"), 24_000);
  assert.equal(toYearly(pay, 18, "hour", 30), 28_080); // 18 x 30 h x 52 weeks
});

test("units the question doesn't accept are refused, not guessed", () => {
  assert.throws(() => toYearly({ type: "money", person_units: ["total"] }, 500, "month"), UnitError);
  assert.throws(() => toYearly(pay, 18, "hour"), /hours/);
});

test("read-back says it as the person did, plus the yearly figure", () => {
  assert.equal(readBack("Rent", 1450, "month", 17_400), "Rent: $1,450 a month ($17,400 a year)");
  assert.equal(readBack("Pay", 2000, "month", 30_000, true), "Pay: $2,000 a month take-home ($30,000 a year before taxes)");
});
