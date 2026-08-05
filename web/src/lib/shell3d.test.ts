/**
 * Pins the wall UV-frame derivation against the server's frame convention
 * (room_planes / roomplan_room / shell_envelope): axis_u = up x n_h from
 * the interior-fronting winding, origin at the bounding rect's (min-u,
 * min-y) corner. The load-bearing case is start-corner invariance — v3
 * winding normalization can rotate which vertex comes first, and openings
 * must land on the same world rect regardless (the old corner-0 math
 * would mirror them on such walls).
 */

import { describe, expect, it } from "vitest";

import { openingRect, projectToWallPlane, wallFrame, type Vec3 } from "./shell3d";

/** A 4x2 m wall in the z=0 plane, x in [0,4], y in [-1,1], fronting +Z
 * (interior at +Z), wound per the server contract with corner 0 at the
 * frame origin. */
const WALL_PLUS_Z: Vec3[] = [
  [0, -1, 0],
  [4, -1, 0],
  [4, 1, 0],
  [0, 1, 0],
];

function expectVec(actual: Vec3, expected: Vec3, digits = 6) {
  for (let i = 0; i < 3; i++) expect(actual[i]).toBeCloseTo(expected[i], digits);
}

describe("wallFrame", () => {
  it("derives the server frame from a canonical quad", () => {
    const f = wallFrame(WALL_PLUS_Z)!;
    expectVec(f.normal, [0, 0, 1]);
    expectVec(f.axisU, [1, 0, 0]);
    expectVec(f.origin, [0, -1, 0]);
    expect(f.widthM).toBeCloseTo(4);
    expect(f.heightM).toBeCloseTo(2);
  });

  it("is invariant to the start corner (v3 winding rotation)", () => {
    // Same cyclic order, started at index 2 — corner 0 is now the
    // top-far corner, NOT the UV origin.
    const rotated: Vec3[] = [
      WALL_PLUS_Z[2],
      WALL_PLUS_Z[3],
      WALL_PLUS_Z[0],
      WALL_PLUS_Z[1],
    ];
    const f = wallFrame(rotated)!;
    expectVec(f.normal, [0, 0, 1]);
    expectVec(f.axisU, [1, 0, 0]);
    expectVec(f.origin, [0, -1, 0]);
    expect(f.widthM).toBeCloseTo(4);
    expect(f.heightM).toBeCloseTo(2);
  });

  it("follows the winding: a reversed polygon fronts the other way", () => {
    const reversed = [...WALL_PLUS_Z].reverse();
    const f = wallFrame(reversed)!;
    expectVec(f.normal, [0, 0, -1]);
    expectVec(f.axisU, [-1, 0, 0]);
    // min-u along -X is the x=4 edge.
    expectVec(f.origin, [4, -1, 0]);
  });

  it("handles an oblique (non-axis-aligned) wall", () => {
    const inv = Math.SQRT1_2;
    const oblique: Vec3[] = [
      [0, -1, 0],
      [2, -1, 2],
      [2, 1, 2],
      [0, 1, 0],
    ];
    const f = wallFrame(oblique)!;
    expectVec(f.normal, [-inv, 0, inv]);
    expectVec(f.axisU, [inv, 0, inv]);
    expectVec(f.origin, [0, -1, 0]);
    expect(f.widthM).toBeCloseTo(2 * Math.SQRT2);
    expect(f.heightM).toBeCloseTo(2);
  });

  it("covers a notched explicit outline with its bounding rect", () => {
    const notched: Vec3[] = [
      [0, -1, 0],
      [4, -1, 0],
      [4, 1, 0],
      [2.5, 1, 0],
      [2.5, 0.4, 0],
      [0, 0.4, 0],
    ];
    const f = wallFrame(notched)!;
    expect(f.widthM).toBeCloseTo(4);
    expect(f.heightM).toBeCloseTo(2);
    expectVec(f.origin, [0, -1, 0]);
    const uv = projectToWallPlane(notched, f);
    // Interior-fronting winding projects counter-clockwise in (u, v)...
    let area2 = 0;
    for (let i = 0; i < uv.length; i++) {
      const [u0, v0] = uv[i];
      const [u1, v1] = uv[(i + 1) % uv.length];
      area2 += u0 * v1 - u1 * v0;
    }
    expect(area2).toBeGreaterThan(0);
    // ...spanning [0, width] x [0, height].
    expect(Math.min(...uv.map(([u]) => u))).toBeCloseTo(0);
    expect(Math.max(...uv.map(([u]) => u))).toBeCloseTo(4);
    expect(Math.min(...uv.map(([, v]) => v))).toBeCloseTo(0);
    expect(Math.max(...uv.map(([, v]) => v))).toBeCloseTo(2);
  });

  it("returns null for degenerate input", () => {
    expect(wallFrame([[0, 0, 0], [1, 0, 0]])).toBeNull();
    // A horizontal polygon is a floor, not a wall.
    expect(
      wallFrame([
        [0, 0, 0],
        [1, 0, 0],
        [1, 0, 1],
        [0, 0, 1],
      ]),
    ).toBeNull();
    // Zero lateral extent.
    expect(
      wallFrame([
        [0, 0, 0],
        [0, 1, 0],
        [0, 1, 0.0000000001],
      ]),
    ).toBeNull();
  });
});

describe("openingRect", () => {
  it("maps normalized rect_uv onto the wall's meters", () => {
    const f = wallFrame(WALL_PLUS_Z)!;
    const [c0, c1, c2, c3] = openingRect(f, [
      [0.25, 0],
      [0.5, 0.5],
    ]);
    expectVec(c0, [1, -1, 0]);
    expectVec(c1, [2, -1, 0]);
    expectVec(c2, [2, 0, 0]);
    expectVec(c3, [1, 0, 0]);
  });

  it("floats the patch toward the interior by offsetM", () => {
    const f = wallFrame(WALL_PLUS_Z)!;
    const rect = openingRect(f, [[0, 0], [1, 1]], 0.006);
    for (const c of rect) expect(c[2]).toBeCloseTo(0.006);
  });

  it("lands the same world rect regardless of the start corner", () => {
    // The regression the corner-0 math fails: rotate the start corner and
    // the opening must not move or mirror.
    const rotated: Vec3[] = [
      WALL_PLUS_Z[2],
      WALL_PLUS_Z[3],
      WALL_PLUS_Z[0],
      WALL_PLUS_Z[1],
    ];
    const a = openingRect(wallFrame(WALL_PLUS_Z)!, [[0.25, 0], [0.5, 0.5]]);
    const b = openingRect(wallFrame(rotated)!, [[0.25, 0], [0.5, 0.5]]);
    for (let i = 0; i < 4; i++) expectVec(b[i], a[i]);
  });

  it("stays on an oblique wall's plane", () => {
    const oblique: Vec3[] = [
      [0, -1, 0],
      [2, -1, 2],
      [2, 1, 2],
      [0, 1, 0],
    ];
    const f = wallFrame(oblique)!;
    const rect = openingRect(f, [[0.5, 0], [1, 1]]);
    expectVec(rect[0], [1, -1, 1]);
    expectVec(rect[2], [2, 1, 2]);
  });
});
