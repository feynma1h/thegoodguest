/**
 * Voice helpers: how real data gets spoken in the product's register
 * (design: "Good Guest — Product System"). Everything here is DERIVED
 * from facts — capture dates, list sizes — never invented. Room naming
 * proposals are a future feature; until then a room's "name" is its
 * capture day.
 */

const SMALL_COUNTS = [
  "no",
  "one",
  "two",
  "three",
  "four",
  "five",
  "six",
  "seven",
  "eight",
  "nine",
];

/** Counts read as words while they're conversational, digits after. */
export function smallCount(n: number): string {
  return SMALL_COUNTS[n] ?? String(n);
}

/** The room's derived name: "the July 12 room". Factual, lowercase, in
 * the serif register — replaced by real naming when that feature lands. */
export function roomTitle(createdAtIso: string): string {
  const day = new Date(createdAtIso).toLocaleDateString(undefined, {
    month: "long",
    day: "numeric",
  });
  return `the ${day} room`;
}

/** Elapsed time in the guest's register: "moments ago", "4 minutes in",
 * "an hour in". Used while a room is being rebuilt. */
export function elapsedPhrase(sinceIso: string, now: number = Date.now()): string {
  const minutes = Math.max(0, Math.floor((now - new Date(sinceIso).getTime()) / 60_000));
  if (minutes < 1) return "moments in";
  if (minutes === 1) return "a minute in";
  if (minutes < 60) return `${minutes} minutes in`;
  const hours = Math.floor(minutes / 60);
  return hours === 1 ? "an hour in" : `${hours} hours in`;
}
