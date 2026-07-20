/**
 * Pins the hold rule's memory: unseen by default, seen after marking,
 * scoped per scene.
 */

import { beforeEach, describe, expect, it } from "vitest";

import { hasSeenReveal, markRevealSeen } from "./seen";

describe("reveal-seen flag", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("defaults to unseen, remembers marking, scopes per scene", () => {
    expect(hasSeenReveal("scene-a")).toBe(false);
    markRevealSeen("scene-a");
    expect(hasSeenReveal("scene-a")).toBe(true);
    expect(hasSeenReveal("scene-b")).toBe(false);
  });
});
