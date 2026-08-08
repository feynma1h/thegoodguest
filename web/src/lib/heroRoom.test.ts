import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { assembleScene } from "@/lib/api/types";
import type { SceneAssets } from "@/lib/api/types";
import {
  HERO_PIECE_URL,
  HERO_ROOM_URL,
  heroVariant,
  loadHeroScene,
  withPiece,
} from "@/lib/heroRoom";
import { CONTOUR_START_MS, DONE_BEAT_MS, planReveal } from "@/lib/reveal";

/** The shipped fixture, read from disk exactly as the browser fetches it. */
const fixture = JSON.parse(
  readFileSync(join(process.cwd(), "public/hero/room.json"), "utf8"),
) as SceneAssets;

function okJson(body: unknown) {
  return { ok: true, json: async () => body } as unknown as Response;
}
const notFound = { ok: false, json: async () => ({}) } as unknown as Response;

describe("heroVariant", () => {
  it("defaults to the shipped hero", () => {
    expect(heroVariant("")).toBe("a");
    expect(heroVariant("?foo=1")).toBe("a");
    expect(heroVariant("?hero=a")).toBe("a");
    expect(heroVariant("?hero=nonsense")).toBe("a");
  });

  it("opts into the one-piece probe on ?hero=b", () => {
    expect(heroVariant("?hero=b")).toBe("b");
    expect(heroVariant("?hero=B")).toBe("b");
    expect(heroVariant("?x=1&hero=b")).toBe("b");
  });
});

describe("the shipped hero fixture", () => {
  it("carries a real room's geometry and NO objects", () => {
    expect(fixture.manifest.objects).toEqual([]);
    expect(fixture.asset_urls).toEqual({});
    expect(fixture.shell?.status).toBe("ready");
  });

  it("assembles through the production contract into shell-only", () => {
    const scene = assembleScene(fixture);
    expect(scene.splats).toEqual([]);
    expect(scene.unrenderable).toEqual([]);
    // A floor and its walls — the boundary the contour traces.
    expect(scene.shell?.filter((p) => p.kind === "floor")).toHaveLength(1);
    expect(scene.shell!.filter((p) => p.kind === "wall").length).toBeGreaterThan(2);
  });

  it("stays small enough to be a hero — kilobytes, not megabytes", () => {
    const bytes = readFileSync(join(process.cwd(), "public/hero/room.json")).length;
    expect(bytes).toBeLessThan(32 * 1024);
  });

  it("ships no signed or remote URL — nothing here is fetched at runtime", () => {
    expect(JSON.stringify(fixture)).not.toMatch(/https?:\/\//);
  });
});

/**
 * The cap. The hero shows the first two movements and stops — and it does
 * so WITHOUT a special code path: a shell with zero objects already ends
 * the score at the surfaces. These pin that this is true of the real
 * fixture, so the day someone adds objects back the cap breaks loudly.
 */
describe("the score caps itself after the surfaces", () => {
  const scene = assembleScene(fixture);
  const plan = planReveal({ shell: scene.shell ?? [], splats: [] });

  it("plays: shell-only is not `nothingToPlay`", () => {
    expect(plan.immediate).toBe(false);
    expect(plan.contour).not.toBeNull();
    expect(plan.surfaces.length).toBe(scene.shell!.length);
  });

  it("has no object cues and no names to speak", () => {
    expect(plan.objects).toEqual([]);
    expect(plan.captionsDoneMs).toBe(0);
  });

  it("ends one quiet beat after the last surface, not after a piece", () => {
    const lastSurface = Math.max(
      ...plan.surfaces.map((c) => c.startMs + c.durationMs),
    );
    expect(plan.doneMs).toBe(lastSurface + DONE_BEAT_MS);
    // The whole hero is seconds, not tens of seconds.
    expect(plan.doneMs).toBeGreaterThan(CONTOUR_START_MS);
    expect(plan.doneMs).toBeLessThan(6000);
  });

  it("collapses honestly under reduced motion — nothing materializes", () => {
    const reduced = planReveal({
      shell: scene.shell ?? [],
      splats: [],
      reducedMotion: true,
    });
    expect(reduced.immediate).toBe(true);
    expect(reduced.contour).toBeNull();
    expect(reduced.doneMs).toBe(0);
    expect(reduced.surfaces.every((c) => c.durationMs === 0)).toBe(true);
  });
});

describe("loadHeroScene", () => {
  it("returns the shell-only scene for the shipped variant", async () => {
    const scene = await loadHeroScene("a", async (url) => {
      expect(url).toBe(HERO_ROOM_URL);
      return okJson(fixture);
    });
    expect(scene?.splats).toEqual([]);
    expect(scene?.shell?.length).toBeGreaterThan(0);
  });

  it("never fetches the probe's piece for the shipped variant", async () => {
    const seen: string[] = [];
    await loadHeroScene("a", async (url) => {
      seen.push(String(url));
      return okJson(fixture);
    });
    expect(seen).toEqual([HERO_ROOM_URL]);
  });

  it("degrades variant B to the shipped hero when no piece is staged", async () => {
    const scene = await loadHeroScene("b", async (url) =>
      url === HERO_ROOM_URL ? okJson(fixture) : notFound,
    );
    expect(scene?.splats).toEqual([]);
    expect(scene?.shell?.length).toBeGreaterThan(0);
  });

  it("settles exactly one named piece when the probe IS staged", async () => {
    const piece = {
      objects: [
        {
          object_id: "hero_piece",
          label: "chair",
          placed: true,
          splat_gcs_uri: "gs://hero/piece.ply",
          world_transform: {
            position: [0, -1, 0],
            rotation_xyzw: [0, 0, 0, 1],
            scale: 1,
          },
        },
      ],
      asset_urls: { "gs://hero/piece.ply": "/hero/piece.ply" },
    };
    const scene = await loadHeroScene("b", async (url) =>
      url === HERO_PIECE_URL ? okJson(piece) : okJson(fixture),
    );
    expect(scene?.splats.map((s) => s.label)).toEqual(["chair"]);

    // One piece is under NAMED_ALL_UNDER, so the guest names it — "as the
    // score already does", with no hero-specific naming rule.
    const plan = planReveal({ shell: scene!.shell ?? [], splats: scene!.splats });
    expect(plan.objects).toHaveLength(1);
    expect(plan.objects[0].named).toBe(true);
  });

  it("returns null — the copy lands at once — when the fixture is missing", async () => {
    expect(await loadHeroScene("a", async () => notFound)).toBeNull();
  });

  it("returns null rather than throwing when the fetch itself fails", async () => {
    expect(
      await loadHeroScene("a", async () => {
        throw new Error("offline");
      }),
    ).toBeNull();
  });

  it("returns null for a shell that never became ready", async () => {
    const unavailable = {
      ...fixture,
      shell: { ...fixture.shell, status: "unavailable", reason: "capture_expired" },
    } as SceneAssets;
    expect(await loadHeroScene("a", async () => okJson(unavailable))).toBeNull();
  });
});

describe("withPiece", () => {
  it("leaves the shipped fixture untouched", () => {
    const before = JSON.stringify(fixture);
    withPiece(fixture, { objects: [], asset_urls: { a: "b" } });
    expect(JSON.stringify(fixture)).toBe(before);
  });
});
