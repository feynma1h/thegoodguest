/**
 * Pins the voice helpers' honesty: titles and counts derive from real
 * data, degrade to digits when counts stop being conversational, and
 * never throw on edge inputs.
 */

import { describe, expect, it } from "vitest";

import {
  arrivalLine,
  countsLine,
  elapsedPhrase,
  roomTitle,
  settledLine,
  smallCount,
  waitNarration,
} from "./voice";

describe("smallCount", () => {
  it("spells conversational counts, keeps digits beyond nine", () => {
    expect(smallCount(0)).toBe("no");
    expect(smallCount(1)).toBe("one");
    expect(smallCount(3)).toBe("three");
    expect(smallCount(9)).toBe("nine");
    expect(smallCount(10)).toBe("10");
    expect(smallCount(42)).toBe("42");
  });
});

describe("roomTitle", () => {
  it("derives the name from the capture day only — no invented semantics", () => {
    const title = roomTitle("2026-07-12T13:38:00Z");
    expect(title.startsWith("the ")).toBe(true);
    expect(title.endsWith(" room")).toBe(true);
    expect(title).toContain("12");
  });
});

describe("elapsedPhrase", () => {
  const t0 = Date.parse("2026-07-20T12:00:00Z");
  it("speaks minutes and hours without ever going negative", () => {
    expect(elapsedPhrase("2026-07-20T12:00:30Z", t0)).toBe("moments in"); // clock skew
    expect(elapsedPhrase("2026-07-20T11:59:30Z", t0)).toBe("moments in");
    expect(elapsedPhrase("2026-07-20T11:58:59Z", t0)).toBe("a minute in");
    expect(elapsedPhrase("2026-07-20T11:56:00Z", t0)).toBe("4 minutes in");
    expect(elapsedPhrase("2026-07-20T10:59:00Z", t0)).toBe("an hour in");
    expect(elapsedPhrase("2026-07-20T09:00:00Z", t0)).toBe("3 hours in");
  });
});

describe("waitNarration", () => {
  it("narrates arrival by status, and owns slowness after ten minutes", () => {
    expect(waitNarration("queued", 0)).toContain("at the door");
    expect(waitNarration("processing", 3)).toContain("meeting each piece");
    expect(waitNarration("processing", 10)).toContain("longer than I");
    expect(waitNarration("processing", 500)).toContain("longer than I");
  });
});

describe("arrival and settled lines", () => {
  it("never claims placement that didn't happen", () => {
    expect(arrivalLine(0)).toContain("honest");
    expect(arrivalLine(8)).toContain("furniture came through ahead of the walls");
    expect(settledLine(0)).toContain("slower pass");
    expect(settledLine(5)).toContain("As you left it");
  });
});

describe("countsLine", () => {
  it("states exactly what was placed and what was only seen", () => {
    expect(countsLine(8, 0)).toBe("eight pieces placed");
    expect(countsLine(1, 0)).toBe("one piece placed");
    expect(countsLine(8, 2)).toBe(
      "eight pieces placed · two more seen but not placed yet",
    );
    expect(countsLine(0, 1)).toBe(
      "no pieces placed · one more seen but not placed yet",
    );
    expect(countsLine(12, 11)).toBe(
      "12 pieces placed · 11 more seen but not placed yet",
    );
  });
});
