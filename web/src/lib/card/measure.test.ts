import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import path from "node:path";

import { MockApiClient, MOCK_READY_SCENE_ID, MOCK_V3_SCENE_ID } from "@/lib/api/mock";
import type { SceneAssets, ShellDoc } from "@/lib/api/types";
import { measureRoom, type Pt2 } from "./measure";

/** The landing hero (0122): scene ce68e24f's shell.json v3, verbatim, and
 * the room `docs/product/og-card.html` drew by hand. */
function heroAssets(): SceneAssets {
  return JSON.parse(
    readFileSync(path.resolve(__dirname, "../../../public/hero/room.json"), "utf8"),
  ) as SceneAssets;
}

async function mockAssets(sceneId: string): Promise<SceneAssets> {
  return new MockApiClient().getSceneAssets(sceneId);
}

describe("measureRoom — the hero room", () => {
  const hero = heroAssets();
  const m = measureRoom(hero.shell, hero.manifest)!;

  it("takes the floor contour verbatim", () => {
    expect(m.contour).toHaveLength(6);
    expect(m.contour[0]).toEqual({ x: -1.4215, z: -0.7809 });
    expect(m.contour[2]).toEqual({ x: 3.0724, z: 0.4597 });
  });

  it("reads the ceiling as the tallest measured wall", () => {
    // 0122 quotes this room as "four walls all at one height (2.99 m)".
    expect(m.ceilingM).toBeCloseTo(2.9936, 6);
  });

  it("computes the floor area by shoelace", () => {
    expect(m.floorAreaM2).toBeCloseTo(10.73, 2);
  });

  it("carries the floor's measured albedo and nothing invented", () => {
    expect(m.floorAlbedoHex).toBe("#715b47");
  });

  it("dimensions the longest wall", () => {
    expect(m.datum!.wallId).toBe("wall_00");
    expect(m.datum!.lengthM).toBeCloseTo(3.5481, 4);
  });

  it("places the window on wall_01 at its declared span", () => {
    const wall = m.walls.find((w) => w.wallId === "wall_01")!;
    expect(wall.openings).toHaveLength(1);
    expect(wall.openings[0].kind).toBe("window");
    // rect_uv [[0.5647, …], [0.9018, …]] — measured equals rendered on the
    // roomplan method, so the span replays exactly.
    expect(wall.openings[0].t0).toBeCloseTo(0.5647, 6);
    expect(wall.openings[0].t1).toBeCloseTo(0.9018, 6);
  });

  it("reads wall_01's true length as the precedent's 3.02 m", () => {
    const wall = m.walls.find((w) => w.wallId === "wall_01")!;
    expect(wall.lengthM).toBeCloseTo(3.024, 3);
  });

  it("points each wall's outward normal away from the room", () => {
    // Every wall's outward normal must have a positive component along the
    // direction from the room's centroid to the wall's midpoint.
    const cx = m.contour.reduce((a, p) => a + p.x, 0) / m.contour.length;
    const cz = m.contour.reduce((a, p) => a + p.z, 0) / m.contour.length;
    for (const w of m.walls) {
      const mx = (w.a.x + w.b.x) / 2 - cx;
      const mz = (w.a.z + w.b.z) / 2 - cz;
      expect(w.outward.x * mx + w.outward.z * mz).toBeGreaterThan(0);
      expect(Math.hypot(w.outward.x, w.outward.z)).toBeCloseTo(1, 9);
    }
  });
});

/**
 * The reproduction test. `docs/product/og-card.html` placed this room's
 * plan by hand at a uniform ~82 px/m; this module derives it. If the
 * generic path is right, the two agree to well under a pixel.
 *
 * If og-card.html is ever re-authored around a DIFFERENT room, this test
 * stops meaning anything and should be deleted rather than retuned.
 */
describe("measureRoom reproduces the hand-authored precedent", () => {
  const OG = path.resolve(__dirname, "../../../../docs/product/og-card.html");

  function precedentPolygon(): Array<[number, number]> {
    const html = readFileSync(OG, "utf8");
    const match = html.match(/<clipPath id="roomclip"><polygon points="([^"]+)"/);
    expect(match, "og-card.html no longer carries a #roomclip polygon").toBeTruthy();
    return match![1]
      .trim()
      .split(/\s+/)
      .map((pair) => {
        const [x, y] = pair.split(",").map(Number);
        return [x, y] as [number, number];
      });
  }

  it("agrees on every vertex at one uniform scale", () => {
    const hero = heroAssets();
    const contour: Pt2[] = measureRoom(hero.shell, hero.manifest)!.contour;
    const og = precedentPolygon();
    expect(og).toHaveLength(contour.length);

    // Origin-free: compare displacements from vertex 0, which tests the
    // projection and the scale without testing where it was placed.
    const S = 82; // px per meter, stated in og-card.html's own comment
    let worst = 0;
    for (let i = 1; i < og.length; i++) {
      const wantX = S * (contour[i].x - contour[0].x);
      const wantY = S * (contour[i].z - contour[0].z);
      const gotX = og[i][0] - og[0][0];
      const gotY = og[i][1] - og[0][1];
      worst = Math.max(worst, Math.hypot(gotX - wantX, gotY - wantY));
    }
    // Achieved: 0.0055 px, on a longest span of 382 px — 0.0014%, which is
    // the precedent's own rounding to 2 decimals and nothing else.
    // og-card.html states 0.7%, which on that span would allow 2.7 px.
    expect(worst).toBeLessThan(0.01);
  });
});

describe("measureRoom — a v2 arkit_planes room", () => {
  it("draws the rendered boundary, not the observed floor coverage", async () => {
    const assets = await mockAssets(MOCK_READY_SCENE_ID);
    const m = measureRoom(assets.shell, assets.manifest)!;
    // The fixture's rendered polygon starts [-2.2, 0, 1.4]; its
    // `measured_polygon` — the floor COVERAGE the scan observed — starts
    // [-2.1, 0, 1.3], 10 cm inside the walls that were themselves measured
    // at -2.2/1.4. The room's boundary is the rendered one; drawing the
    // coverage would put a ghost outline inside every closed wall.
    expect(m.contour[0]).toEqual({ x: -2.2, z: 1.4 });
    const wall = m.walls.find((w) => w.wallId === "wall_01")!;
    expect(wall.a).toEqual({ x: -2.2, z: 1.4 });
  });

  it("still calls that wall's length a measurement", async () => {
    const assets = await mockAssets(MOCK_READY_SCENE_ID);
    const m = measureRoom(assets.shell, assets.manifest)!;
    // wall_00 was extended DOWNWARD to the floor (0 vs a detected 0.3) and
    // not sideways, so its length is measured even though its height is
    // partly closure. The two claims are separated on purpose.
    const w0 = m.walls.find((w) => w.wallId === "wall_00")!;
    expect(w0.lengthIsMeasured).toBe(true);
    expect(w0.heightM).toBeCloseTo(1.9, 9);
  });

  it("refuses to dimension a wall closure widened", async () => {
    const assets = await mockAssets(MOCK_READY_SCENE_ID);
    const shell = structuredClone(assets.shell) as ShellDoc & {
      walls: Array<{ measured_quad: Array<[number, number, number]> }>;
    };
    // Pull wall_00's DETECTED extent in by 40 cm at one end: the shell now
    // says it rendered more wall than it saw, so its length is no longer a
    // number the scan can stand behind.
    shell.walls[0].measured_quad = [
      [-1.8, 0.3, -2.6],
      [1.8, 0.3, -2.6],
      [1.8, 2.2, -2.6],
      [-1.8, 2.2, -2.6],
    ];
    const m = measureRoom(shell, assets.manifest)!;
    const w0 = m.walls.find((w) => w.wallId === "wall_00")!;
    expect(w0.lengthIsMeasured).toBe(false);
    // wall_00 is the longest at 4.0 m; the datum falls back to wall_01.
    expect(w0.lengthM).toBeCloseTo(4.0, 9);
    expect(m.datum!.wallId).toBe("wall_01");
  });

  it("prints no dimension at all when no wall qualifies", async () => {
    const assets = await mockAssets(MOCK_READY_SCENE_ID);
    const shell = structuredClone(assets.shell) as ShellDoc & {
      walls: Array<{
        quad: Array<[number, number, number]>;
        measured_quad: Array<[number, number, number]>;
      }>;
    };
    for (const wall of shell.walls) {
      wall.measured_quad = wall.quad.map(
        ([x, y, z]) => [x * 0.5, y, z * 0.5] as [number, number, number],
      );
    }
    expect(measureRoom(shell, assets.manifest)!.datum).toBeNull();
  });

  it("excludes a closure extension from the ceiling claim", async () => {
    const assets = await mockAssets(MOCK_READY_SCENE_ID);
    const m = measureRoom(assets.shell, assets.manifest)!;
    // wall_00 renders 0 -> 2.2 but was detected 0.3 -> 2.2, so its measured
    // height is 1.9; wall_01 was detected over its whole 2.2. The tallest
    // MEASURED wall is the claim.
    const w0 = m.walls.find((w) => w.wallId === "wall_00")!;
    expect(w0.heightM).toBeCloseTo(1.9, 9);
    expect(m.ceilingM).toBeCloseTo(2.2, 9);
  });

  it("keeps a door as an opening with no glazing", async () => {
    const assets = await mockAssets(MOCK_READY_SCENE_ID);
    const m = measureRoom(assets.shell, assets.manifest)!;
    const w0 = m.walls.find((w) => w.wallId === "wall_00")!;
    expect(w0.openings.map((o) => o.kind)).toEqual(["door"]);
  });

  it("counts only placed objects", async () => {
    const assets = await mockAssets(MOCK_READY_SCENE_ID);
    const m = measureRoom(assets.shell, assets.manifest)!;
    const placed = (assets.manifest.objects ?? []).filter((o) => o.placed);
    expect(m.pieceCount).toBe(placed.length);
    expect(m.pieceCount).toBeLessThan((assets.manifest.objects ?? []).length);
  });
});

describe("measureRoom — a v3 roomplan room", () => {
  it("reads all five polygon walls and their three opening kinds", async () => {
    const assets = await mockAssets(MOCK_V3_SCENE_ID);
    const m = measureRoom(assets.shell, assets.manifest)!;
    expect(m.walls).toHaveLength(5);
    const kinds = m.walls.flatMap((w) => w.openings.map((o) => o.kind)).sort();
    expect(kinds).toEqual(["door", "opening", "window"]);
  });

  it("keeps every opening span inside its wall", async () => {
    const assets = await mockAssets(MOCK_V3_SCENE_ID);
    const m = measureRoom(assets.shell, assets.manifest)!;
    for (const w of m.walls) {
      for (const o of w.openings) {
        expect(o.t0).toBeGreaterThanOrEqual(0);
        expect(o.t1).toBeLessThanOrEqual(1);
        expect(o.t1).toBeGreaterThan(o.t0);
      }
    }
  });
});

describe("measureRoom refuses rather than guesses", () => {
  it("returns null with no shell at all", () => {
    expect(measureRoom(null, { scene_id: "x" })).toBeNull();
    expect(measureRoom(undefined, { scene_id: "x" })).toBeNull();
  });

  it("returns null for a shell that is never coming", () => {
    const doc = {
      shell_version: 3,
      method: "roomplan",
      scene_id: "x",
      status: "unavailable",
      reason: "no_geometry_source",
      floor: null,
      walls: [],
    } as unknown as ShellDoc;
    expect(measureRoom(doc, null)).toBeNull();
  });

  it("returns null for a degenerate floor", () => {
    const base = heroAssets().shell as ShellDoc;
    const twoCorners = {
      ...base,
      floor: { ...base.floor!, polygon: base.floor!.polygon.slice(0, 2) },
    } as ShellDoc;
    expect(measureRoom(twoCorners, null)).toBeNull();

    const zeroArea = {
      ...base,
      floor: {
        ...base.floor!,
        polygon: [
          [0, 0, 0],
          [1, 0, 0],
          [2, 0, 0],
        ],
      },
    } as unknown as ShellDoc;
    expect(measureRoom(zeroArea, null)).toBeNull();
  });
});
