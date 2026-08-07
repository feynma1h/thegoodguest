/**
 * Pins for the deletion copy (decision 0095). These test CLAIMS, not
 * strings: that the consequence names all three erased things, that a
 * partial pass is never reported as damage, and that the phone consequence
 * is stated rather than implied.
 */

import { describe, expect, it } from "vitest";

import {
  PHONE_CONSEQUENCE,
  deletionConsequence,
  deletionOutcome,
  roomPhrase,
} from "./account";

const result = (over: Partial<Parameters<typeof deletionOutcome>[0]> = {}) => ({
  deleted: true,
  identityDeleted: true,
  counts: {
    rooms: 0,
    conversations: 0,
    conversationMessages: 0,
    uploadSessions: 0,
    files: 0,
  },
  ...over,
});

describe("roomPhrase", () => {
  it("agrees in number", () => {
    expect(roomPhrase(1)).toBe("1 room");
    expect(roomPhrase(0)).toBe("0 rooms");
    expect(roomPhrase(7)).toBe("7 rooms");
  });
});

describe("deletionConsequence", () => {
  it("names every category that is actually erased", () => {
    // Understating this is the failure mode: a user who reads "your rooms"
    // may believe conversations survive.
    const text = deletionConsequence(7);
    expect(text).toContain("reconstruction");
    expect(text).toContain("measurement");
    expect(text).toContain("conversation");
    expect(text).toContain("cannot be undone");
  });

  it("names no number while the count is still loading", () => {
    expect(deletionConsequence(null)).not.toMatch(/\d/);
  });

  it("reads correctly for an empty account", () => {
    const text = deletionConsequence(0);
    expect(text).toContain("This account");
    expect(text).not.toContain("0 rooms");
  });

  it("agrees in number for a single room", () => {
    expect(deletionConsequence(1)).toContain("1 room —");
  });
});

describe("PHONE_CONSEQUENCE", () => {
  it("states that the phone starts over and does not get the rooms back", () => {
    expect(PHONE_CONSEQUENCE).toMatch(/new, empty account/);
    expect(PHONE_CONSEQUENCE).toMatch(/not your rooms back/);
  });
});

describe("deletionOutcome", () => {
  it("reports a partial pass as unfinished, never as damage", () => {
    const { done, line } = deletionOutcome(result({ deleted: false }));
    expect(done).toBe(false);
    expect(line).toContain("intact");
    expect(line).not.toMatch(/wrong|error|failed/i);
  });

  it("summarizes what went", () => {
    const { done, line } = deletionOutcome(
      result({ counts: { ...result().counts, rooms: 7, conversations: 2 } }),
    );
    expect(done).toBe(true);
    expect(line).toContain("7 rooms");
    expect(line).toContain("2 conversations");
  });

  it("omits conversations when there were none", () => {
    const { line } = deletionOutcome(
      result({ counts: { ...result().counts, rooms: 3 } }),
    );
    expect(line).toContain("3 rooms");
    expect(line).not.toContain("conversation");
  });
});
