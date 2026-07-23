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

/** Whole minutes since an ISO timestamp, floored at zero (clock skew). */
export function minutesSince(sinceIso: string, now: number = Date.now()): number {
  return Math.max(0, Math.floor((now - new Date(sinceIso).getTime()) / 60_000));
}

/** Elapsed time in the guest's register: "moments ago", "4 minutes in",
 * "an hour in". Used while a room is being rebuilt. */
export function elapsedPhrase(sinceIso: string, now: number = Date.now()): string {
  const minutes = minutesSince(sinceIso, now);
  if (minutes < 1) return "moments in";
  if (minutes === 1) return "a minute in";
  if (minutes < 60) return `${minutes} minutes in`;
  const hours = Math.floor(minutes / 60);
  return hours === 1 ? "an hour in" : `${hours} hours in`;
}

/** The wait, narrated as arrival — never as pipeline states (design §3).
 * Claims only what the backend is genuinely doing. */
export function waitNarration(
  status: "queued" | "processing",
  minutesElapsed: number,
): string {
  if (status === "queued") return "Your scan made the trip. I’m at the door.";
  if (minutesElapsed >= 10) {
    return "Taking longer than I’d like — some rooms need more thought. Still at it.";
  }
  return "I’m inside — meeting each piece, working out where it stands.";
}

/** First words after the reveal. Which framing is honest depends on what
 * actually rendered: with a room shell (decision 0066) the walls are
 * literally standing; without one, the furniture-before-walls line stays
 * literally true. Never claim walls that aren't there — or deny ones
 * that are. */
export function arrivalLine(placed: number, hasShell: boolean = false): string {
  if (hasShell) {
    if (placed === 0) {
      return "The room itself stood up — floor and walls — but I couldn’t place a single piece inside it with enough confidence to show you. Better honest than wrong; a slower pass would help me.";
    }
    return "The room stood up first — floor, then walls — and your furniture settled in where it belongs. Come look at how it sits.";
  }
  if (placed === 0) {
    return "I could see your room, but I couldn’t place a single piece with enough confidence to show you — better honest than wrong. A slower pass would help me.";
  }
  return "Your furniture came through ahead of the walls — they’re still on their way. Honestly, my favorite way to meet a room: just the things you chose, nothing behind them.";
}

/** The settled greeting on a return visit — a live invitation, now that
 * the guest can answer (conversation stage 1, decision 0058). */
export function settledLine(placed: number): string {
  if (placed === 0) {
    return "Still nothing I could honestly place — ask me why, or give me one slower pass and I’ll meet the room properly.";
  }
  return "As you left it. I’ve been looking — ask me anything about how it sits.";
}

/** The settled greeting when the conversation layer is unavailable (the
 * degraded branch): no invitation a dead composer can't honor. */
export function settledQuietLine(placed: number): string {
  if (placed === 0) {
    return "Still nothing I could honestly place — when you have a minute, one slower pass and I’ll meet the room properly.";
  }
  return "As you left it. Have another look around — I’ll be able to talk it through with you soon.";
}

/** The quiet factual line under the guest's words: exactly what was
 * placed and what was only seen. */
export function countsLine(placed: number, seen: number): string {
  const placedPart =
    placed === 1 ? "one piece placed" : `${smallCount(placed)} pieces placed`;
  if (seen === 0) return placedPart;
  const seenPart =
    seen === 1
      ? "one more seen but not placed yet"
      : `${smallCount(seen)} more seen but not placed yet`;
  return `${placedPart} · ${seenPart}`;
}
