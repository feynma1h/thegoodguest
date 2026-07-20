/**
 * Pins the status-classification semantics the UI relies on, mirroring
 * the iOS ScenePollState model: which statuses are terminal, and that
 * every status renders with a human label (not the wire string).
 */

import { describe, expect, it } from "vitest";

import { SCENE_STATUSES } from "./api/types";
import { statusMeta } from "./status";

describe("statusMeta", () => {
  it("classifies terminal vs in-flight like the iOS poller", () => {
    expect(statusMeta("ready").terminal).toBe(true);
    expect(statusMeta("failed").terminal).toBe(true);
    expect(statusMeta("failed_invalid").terminal).toBe(true);
    expect(statusMeta("queued").terminal).toBe(false);
    expect(statusMeta("processing").terminal).toBe(false);
    // Recoverable: the upload can be completed, so not terminal.
    expect(statusMeta("failed_incomplete").terminal).toBe(false);
  });

  it("gives every status a human label and description", () => {
    for (const status of SCENE_STATUSES) {
      const meta = statusMeta(status);
      expect(meta.label).not.toBe(status);
      expect(meta.description.length).toBeGreaterThan(10);
    }
  });

  it("tones: success only for ready, error for the two hard failures", () => {
    expect(statusMeta("ready").tone).toBe("success");
    expect(statusMeta("failed").tone).toBe("error");
    expect(statusMeta("failed_invalid").tone).toBe("error");
    expect(statusMeta("failed_incomplete").tone).toBe("warning");
  });
});
