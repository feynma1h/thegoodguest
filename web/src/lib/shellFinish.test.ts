/**
 * The finish layout math and the validator. The validator is the safety
 * rail: a finish file made for a different scan must draw NOTHING rather
 * than a wrong room, so the wall-count and colour checks are pinned.
 */

import { describe, expect, it } from "vitest";

import {
  baseboardSpans,
  casingPieces,
  chooseCutaway,
  wallAdjacency,
  finishSignature,
  isRectangularWall,
  openingMetres,
  parseFinish,
} from "./shellFinish";
import { wallFrame, type Vec3 } from "./shell3d";

const trim = {
  hex: "#f3f1ec",
  baseboard_h_m: 0.09,
  baseboard_d_m: 0.014,
  casing_w_m: 0.07,
  casing_d_m: 0.016,
};

const finish = (walls = 2) => ({
  finish_version: 2,
  scene_id: "s",
  wall_count: walls,
  trim: { ...trim },
  walls: Array.from({ length: walls }, (_, i) => ({
    wall_id: `wall_0${i}`,
    paint: { hex: "#aabbcc", source: "measured", sheen: 0.1, grain: 0.03 },
    openings: [],
  })),
  floor: {
    hex: "#999999",
    family: "stone",
    style: { kind: "stone", mottle: 0.05, speckle: 0.02, seed: 1, slab_u_m: 0.6, slab_v_m: 0.6 },
  },
});

describe("parseFinish", () => {
  it("accepts a finish that fits the shell", () => {
    expect(parseFinish(finish(2), 2)).not.toBeNull();
  });
  it("refuses a finish made for a different wall count", () => {
    expect(parseFinish(finish(3), 2)).toBeNull();
  });
  it("refuses a bad version, a bad colour and non-objects", () => {
    expect(parseFinish({ ...finish(2), finish_version: 1 }, 2)).toBeNull();
    const bad = finish(2);
    bad.walls[0].paint.hex = "blue";
    expect(parseFinish(bad, 2)).toBeNull();
    expect(parseFinish(null, 2)).toBeNull();
    expect(parseFinish("x", 2)).toBeNull();
  });
  it("refuses absurd trim sizes", () => {
    const bad = finish(2);
    bad.trim.baseboard_h_m = 3;
    expect(parseFinish(bad, 2)).toBeNull();
  });
});

describe("finishSignature", () => {
  it("is empty for none and changes with the colours", () => {
    expect(finishSignature(null)).toBe("");
    const a = parseFinish(finish(2), 2)!;
    const b = parseFinish(finish(2), 2)!;
    b.walls[0].paint.hex = "#112233";
    expect(finishSignature(a)).not.toBe(finishSignature(b));
  });
});

describe("baseboardSpans", () => {
  it("runs the whole wall when nothing reaches the floor", () => {
    // A window (v0 well above the floor) leaves the board unbroken.
    expect(baseboardSpans(3, [{ u0: 1, u1: 2, v0: 0.9, v1: 2 }], 0.07)).toEqual([[0, 3]]);
  });
  it("stops the board at the door casing", () => {
    const spans = baseboardSpans(3, [{ u0: 1, u1: 1.8, v0: 0, v1: 2 }], 0.07);
    expect(spans).toEqual([
      [0, 1 - 0.07],
      [1.8 + 0.07, 3],
    ]);
  });
  it("drops slivers beside a door at the wall's end", () => {
    const spans = baseboardSpans(3, [{ u0: 2.15, u1: 2.93, v0: 0, v1: 2 }], 0.07);
    expect(spans).toEqual([[0, 2.15 - 0.07]]);
  });
});

describe("casingPieces", () => {
  it("frames a door on three sides and a window with a sill", () => {
    const door = casingPieces({ u0: 1, u1: 1.8, v0: 0, v1: 2 }, 3, 3, 0.07);
    expect(door).toHaveLength(3);
    const win = casingPieces({ u0: 1, u1: 2, v0: 1, v1: 2 }, 3, 3, 0.07);
    expect(win).toHaveLength(4);
    expect(win.some((p) => p.deeper > 0)).toBe(true);
  });
  it("never lets trim past the wall's own rect (the corner)", () => {
    const pieces = casingPieces({ u0: 2.2, u1: 2.97, v0: 0, v1: 2 }, 3, 3, 0.07);
    for (const p of pieces) {
      expect(p.cu - p.w / 2).toBeGreaterThanOrEqual(-1e-9);
      expect(p.cu + p.w / 2).toBeLessThanOrEqual(3 + 1e-9);
    }
  });
});

describe("openingMetres / isRectangularWall", () => {
  const rect: Vec3[] = [
    [0, 0, 0],
    [4, 0, 0],
    [4, 3, 0],
    [0, 3, 0],
  ];
  it("scales rect_uv by the wall's own size", () => {
    const f = wallFrame(rect);
    // Newell on this winding fronts -Z or +Z; either way width/height hold.
    const f1 = f ?? wallFrame([...rect].reverse())!;
    const m = openingMetres(f1, [
      [0.25, 0],
      [0.5, 2 / 3],
    ]);
    expect(m.u0).toBeCloseTo(1);
    expect(m.u1).toBeCloseTo(2);
    expect(m.v1).toBeCloseTo(2);
  });
  it("recognises a plain rectangle and refuses an L-shaped cut", () => {
    const f = wallFrame(rect)!;
    expect(isRectangularWall(rect, f)).toBe(true);
    const gable: Vec3[] = [
      [0, 0, 0],
      [4, 0, 0],
      [4, 2, 0],
      [2, 3, 0],
      [0, 2, 0],
    ];
    expect(isRectangularWall(gable, wallFrame(gable)!)).toBe(false);
  });
});

describe("cutaway staging", () => {
  // A 4 x 3 m room, walls wound to front the interior, plus a window on +x.
  const room = (): { corners: Vec3[]; openings: { classification: string }[] }[] => [
    { corners: [[0, 0, 0], [4, 0, 0], [4, 2, 0], [0, 2, 0]], openings: [] }, // z=0, fronts +z
    { corners: [[4, 0, 0], [4, 0, 3], [4, 2, 3], [4, 2, 0]], openings: [{ classification: "window" }] }, // x=4, fronts -x
    { corners: [[4, 0, 3], [0, 0, 3], [0, 2, 3], [4, 2, 3]], openings: [] }, // z=3, fronts -z
    { corners: [[0, 0, 3], [0, 0, 0], [0, 2, 0], [0, 2, 3]], openings: [] }, // x=0, fronts +x
  ];
  it("finds the four corners of a rectangular room", () => {
    expect(wallAdjacency(room())).toHaveLength(4);
  });
  it("keeps the corner that holds the window and looks into it", () => {
    const c = chooseCutaway(room())!;
    expect(c.keep.includes(1)).toBe(true);
    // Camera lies on the interior side of both kept walls.
    const frames = c.keep.map((i) => wallFrame(room()[i].corners)!);
    const d = [Math.sin(c.azimuthRad), Math.cos(c.azimuthRad)];
    for (const f of frames) expect(d[0] * f.normal[0] + d[1] * f.normal[2]).toBeGreaterThan(0.5);
  });
  it("honours an explicit pair and refuses opposite walls", () => {
    expect(chooseCutaway(room(), [0, 3])!.keep).toEqual([0, 3]);
    expect(chooseCutaway(room(), [0, 2])).toBeNull();
  });
});
