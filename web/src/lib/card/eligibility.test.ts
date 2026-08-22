import { describe, expect, it } from "vitest";

import {
  cardEligibility,
  SUPPRESSION_ARMED_SINCE,
  type GatedScene,
} from "./eligibility";

const ready = (createdAt: string): GatedScene => ({
  status: "ready",
  created_at: createdAt,
});

/**
 * The gate is the reason this feature is allowed to exist at all. A room
 * scanned before person suppression shipped may carry a person in a
 * measured wall albedo (0089), and the shell is exactly what the card
 * draws — so these are the tests that matter most in this directory.
 */
describe("cardEligibility", () => {
  it("refuses a room scanned before suppression shipped", () => {
    // The landing hero's disqualified sibling: the RoomPlan spike room was
    // segmented 2026-08-05, before the armed revision (0122).
    expect(cardEligibility(ready("2026-08-05T11:00:00Z"))).toEqual({
      eligible: false,
      reason: "pre_suppression",
    });
  });

  it("refuses a room created in the same instant as the deploy", () => {
    // Not provably later than the deploy is not eligible.
    expect(cardEligibility(ready(SUPPRESSION_ARMED_SINCE))).toEqual({
      eligible: false,
      reason: "pre_suppression",
    });
  });

  it("refuses one millisecond before, admits one millisecond after", () => {
    const t = Date.parse(SUPPRESSION_ARMED_SINCE);
    expect(cardEligibility(ready(new Date(t - 1).toISOString())).eligible).toBe(
      false,
    );
    expect(cardEligibility(ready(new Date(t + 1).toISOString())).eligible).toBe(
      true,
    );
  });

  it("admits a room scanned after", () => {
    expect(cardEligibility(ready("2026-08-21T09:00:00Z"))).toEqual({
      eligible: true,
    });
  });

  it("refuses a room whose date it cannot read", () => {
    for (const bad of ["", "yesterday", "not-a-date"]) {
      expect(cardEligibility(ready(bad))).toEqual({
        eligible: false,
        reason: "undated",
      });
    }
  });

  it("refuses every non-ready status", () => {
    for (const status of [
      "queued",
      "processing",
      "failed",
      "failed_incomplete",
      "failed_invalid",
    ]) {
      expect(
        cardEligibility({ status, created_at: "2026-08-21T09:00:00Z" }),
      ).toEqual({ eligible: false, reason: "not_ready" });
    }
  });

  it("never admits on absence of evidence", () => {
    // Whatever is thrown at it, the only route to eligible is a parseable
    // date strictly after the armed deploy on a ready scene.
    const inputs: GatedScene[] = [
      { status: "ready", created_at: undefined as unknown as string },
      { status: undefined as unknown as string, created_at: "2026-08-21T09:00:00Z" },
      { status: "ready", created_at: null as unknown as string },
    ];
    for (const input of inputs) {
      expect(cardEligibility(input).eligible).toBe(false);
    }
  });

  it("pins the armed revision's deploy time", () => {
    // perception-obj-00036-l9l, created 2026-08-07T21:27:53Z — the
    // revision that carried decision 0089. Changing this changes which
    // rooms may leave an account, so it changes deliberately or not at all.
    expect(SUPPRESSION_ARMED_SINCE).toBe("2026-08-07T21:27:53Z");
  });
});
