// Answers arrive in the person's units ("$1,450 a month", "$18 an hour"); the engine takes
// US dollars per year. Which units a question accepts comes from the dictionary
// (answer.person_units); how many of each fit in a year is a calendar fact, defined here once.

import type { AnswerSpec } from "./engine.js";

/** The person's units don't fit the question (asked again by the model). */
export class UnitError extends Error {}

export const PER_YEAR: Record<string, number> = {
  week: 52,
  two_weeks: 26,
  half_month: 24,
  month: 12,
  year: 1,
  total: 1, // a balance (savings), not a flow
};
const WEEKS_PER_YEAR = PER_YEAR.week;

export const UNIT_WORDS: Record<string, string> = {
  hour: "an hour",
  week: "a week",
  two_weeks: "every two weeks",
  half_month: "twice a month",
  month: "a month",
  year: "a year",
  total: "in total",
};

const dollars = (x: number) => `$${Math.round(x).toLocaleString("en-US")}`;

/** Yearly dollars for a money answer given per `unit`. `weeklyHours` is needed for "hour". */
export function toYearly(spec: AnswerSpec, amount: number, unit: string, weeklyHours?: number): number {
  const allowed = spec.person_units ?? ["year"];
  if (!allowed.includes(unit)) throw new UnitError(`unit must be one of ${allowed.join(", ")}`);
  if (unit === "hour") {
    if (weeklyHours === undefined) throw new UnitError("hourly pay needs the hours worked per week first");
    return amount * weeklyHours * WEEKS_PER_YEAR;
  }
  return amount * PER_YEAR[unit];
}

/** "rent: $1,450 a month ($17,400 a year)", read back so the person can correct it. */
export function readBack(label: string, amount: number, unit: string, yearly: number, takeHome = false): string {
  const said = `${dollars(amount)} ${UNIT_WORDS[unit]}${takeHome ? " take-home" : ""}`;
  if (unit === "year" || unit === "total") return `${label}: ${said}${takeHome ? ` (${dollars(yearly)} before taxes)` : ""}`;
  return `${label}: ${said} (${dollars(yearly)} a year${takeHome ? " before taxes" : ""})`;
}
