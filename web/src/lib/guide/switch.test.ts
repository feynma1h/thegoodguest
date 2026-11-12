import { describe, expect, it } from "vitest";

import { DIORAMA_VIEWER_PATH, ROOM_GUIDE_ENABLED, roomGuideEnabled, viewerSrc } from "./switch";

describe("the room guide's switch", () => {
  it("is off until the operator turns it on (decision 0376)", () => {
    expect(ROOM_GUIDE_ENABLED).toBe(false);
    expect(roomGuideEnabled()).toBe(false);
  });

  it("opens the viewer on the scene, skipping the reveal only for a kept arrangement", () => {
    const signed = "https://storage.googleapis.com/b/scenes/s1/scene.json?X-Goog-Signature=a%2Bb&x=1";
    const fresh = new URL(viewerSrc(signed, false), "https://app.example");
    expect(fresh.pathname).toBe(DIORAMA_VIEWER_PATH);
    expect(fresh.searchParams.get("scene")).toBe(signed);
    expect(fresh.searchParams.has("intro")).toBe(false);
    const kept = new URL(viewerSrc(signed, true), "https://app.example");
    expect(kept.searchParams.get("intro")).toBe("0");
  });
});
