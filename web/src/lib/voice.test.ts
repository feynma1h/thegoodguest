/**
 * Pins the voice helpers' honesty: titles and counts derive from real
 * data, degrade to digits when counts stop being conversational, and
 * never throw on edge inputs.
 */

import { describe, expect, it } from "vitest";

import { elapsedPhrase, roomTitle, smallCount } from "./voice";

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
