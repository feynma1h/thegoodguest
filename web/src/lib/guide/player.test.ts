import { describe, expect, it, vi } from "vitest";

import { attachPlayer, HIDE_VIEWER_CHROME, playPlan, type GuidePlayer } from "./player";
import type { MotionPlan } from "./types";

/** A frame holding a parsed page, standing in for the viewer's iframe. */
function frameWith(html: string, url = "https://app.example/diorama/viewer.html") {
  const doc = new DOMParser().parseFromString(html, "text/html");
  Object.defineProperty(doc, "URL", { value: url });
  Object.defineProperty(doc, "readyState", { value: "complete" });
  const win: Record<string, unknown> = { document: doc };
  const frame = { contentWindow: win, contentDocument: doc } as unknown as HTMLIFrameElement;
  return { frame, doc, win };
}

const VIEWER = '<html><head></head><body><div id="stage"></div><div id="loading">building the room…</div></body></html>';

const fakePlayer = (): GuidePlayer => ({
  play: vi.fn().mockResolvedValue(true),
  place: vi.fn().mockResolvedValue(true),
  show: vi.fn(),
  clear: vi.fn(),
});

describe("attachPlayer", () => {
  it("injects the player once into the viewer and hands it back when it answers", async () => {
    const { frame, doc, win } = frameWith(VIEWER);
    win.__diorama = {};
    const first = attachPlayer(frame, { src: "/guide/player.js", pollMs: 5 });
    const second = attachPlayer(frame, { src: "/guide/player.js", pollMs: 5 });
    await new Promise((r) => setTimeout(r, 30));
    const scripts = doc.querySelectorAll("script[data-guide-player]");
    expect(scripts).toHaveLength(1);
    expect((scripts[0] as HTMLScriptElement).type).toBe("module");
    expect(scripts[0].getAttribute("src")).toBe("/guide/player.js");
    expect(doc.head.querySelector("style")?.textContent).toBe(HIDE_VIEWER_CHROME);

    const player = fakePlayer();
    win.__guidePlayer = player;
    await expect(first).resolves.toBe(player);
    await expect(second).resolves.toBe(player);
  });

  it("waits while the viewer is still building the room", async () => {
    const { frame, win } = frameWith(VIEWER);
    const attached = attachPlayer(frame, { pollMs: 5 });
    await new Promise((r) => setTimeout(r, 20));
    win.__diorama = {};
    const player = fakePlayer();
    win.__guidePlayer = player;
    await expect(attached).resolves.toBe(player);
  });

  it("refuses a page that is not the viewer, and a viewer that could not load the room", async () => {
    const notFound = frameWith("<html><body><h1>404</h1></body></html>");
    await expect(attachPlayer(notFound.frame, { pollMs: 5 })).rejects.toThrow("viewer_missing");
    const failed = frameWith(VIEWER.replace("building the room…", "Could not load the room: 403"));
    await expect(attachPlayer(failed.frame, { pollMs: 5 })).rejects.toThrow("viewer_failed");
  });

  it("gives up after its time, and when aborted", async () => {
    const slow = frameWith(VIEWER);
    await expect(attachPlayer(slow.frame, { pollMs: 5, timeoutMs: 20 })).rejects.toThrow("viewer_timeout");
    const abort = new AbortController();
    const pending = attachPlayer(frameWith(VIEWER).frame, { pollMs: 5, signal: abort.signal });
    abort.abort();
    await expect(pending).rejects.toThrow("aborted");
  });
});

describe("playPlan", () => {
  it("draws where the pieces stood, then moves them", async () => {
    const player = fakePlayer();
    const plan = {
      plan_version: 1, easing: "smoothstep", duration: 1, order: ["desk"],
      tracks: { desk: [{ t: 0, x: 0, y: 0, z: 0, yaw: 0 }, { t: 1, x: 1, y: 0, z: 0, yaw: 0 }] },
      checked: { frames: 61, fps: 60 },
      footprints: [{ x: 0, z: 0, hx: 0.6, hz: 0.3, yaw: 0 }],
    } satisfies MotionPlan;
    await playPlan(player, plan);
    expect(player.show).toHaveBeenCalledWith({ footprints: plan.footprints });
    expect(player.play).toHaveBeenCalledWith(plan);
    await playPlan(player, null);
    await playPlan(null, plan);
    expect(player.play).toHaveBeenCalledTimes(1);
  });
});
