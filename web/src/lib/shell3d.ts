/**
 * Pure wall-plane math for shell rendering — shell.json v2 quads AND v3
 * polygon walls (decision 0077). SplatViewer consumes these to place
 * door/window opening patches and to project wall polygons for
 * triangulation; nothing here imports three.js (decision 0053's
 * containment rule keeps the renderer library inside SplatViewer.tsx).
 *
 * The frame convention mirrors the server exactly (room_planes /
 * roomplan_room / shell_envelope): walls are vertical and wound so the
 * front face points into the room (the polygon's Newell normal IS the
 * interior normal). The UV frame openings are normalized on is the
 * polygon's bounding rect in-plane:
 *
 *   axis_u = up x n_h   (n_h the horizontalized interior normal)
 *   axis_v = world up
 *   origin = the (min-u, min-y) corner of the bounding rect
 *
 * For v2 quads corner 0 IS that origin (contract), so this generalization
 * reproduces the old corner-0-based math exactly. For v3 polygons corner 0
 * may be any vertex — the server's winding normalization can rotate the
 * start — so deriving the frame from the bounding rect is the only correct
 * reading; assuming corner 0 would mirror openings on some walls.
 */

export type Vec3 = [number, number, number];

export interface WallFrame {
  /** Interior-pointing unit normal, horizontalized (walls are vertical). */
  normal: Vec3;
  /** Unit lateral axis in the wall plane: up x normal. */
  axisU: Vec3;
  /** World point at the bounding rect's (min-u, min-y) corner — the UV
   * origin the server normalizes opening rects against. */
  origin: Vec3;
  widthM: number;
  heightM: number;
}

/** Newell normal (unnormalized): equals 2 * area * n̂ for a planar polygon,
 * pointing along the winding's front face — for shell walls, the interior
 * (the server's test-pinned winding contract). */
export function newellNormal(corners: Vec3[]): Vec3 {
  let nx = 0;
  let ny = 0;
  let nz = 0;
  for (let i = 0; i < corners.length; i++) {
    const [ax, ay, az] = corners[i];
    const [bx, by, bz] = corners[(i + 1) % corners.length];
    nx += (ay - by) * (az + bz);
    ny += (az - bz) * (ax + bx);
    nz += (ax - bx) * (ay + by);
  }
  return [nx, ny, nz];
}

/**
 * The wall's UV frame, derived from its polygon alone. Returns null for
 * degenerate input (fewer than 3 corners, a near-horizontal plane, or a
 * zero-extent rect) — callers skip rather than guess.
 */
export function wallFrame(corners: Vec3[]): WallFrame | null {
  if (corners.length < 3) return null;
  const n = newellNormal(corners);
  const h = Math.hypot(n[0], n[2]);
  if (h < 1e-9) return null;
  const normal: Vec3 = [n[0] / h, 0, n[2] / h];
  const axisU: Vec3 = [normal[2], 0, -normal[0]]; // up x normal
  let minU = Infinity;
  let maxU = -Infinity;
  let minY = Infinity;
  let maxY = -Infinity;
  for (const c of corners) {
    const u = c[0] * axisU[0] + c[2] * axisU[2];
    if (u < minU) minU = u;
    if (u > maxU) maxU = u;
    if (c[1] < minY) minY = c[1];
    if (c[1] > maxY) maxY = c[1];
  }
  const widthM = maxU - minU;
  const heightM = maxY - minY;
  if (widthM < 1e-9 || heightM < 1e-9) return null;
  const c0 = corners[0];
  const u0 = c0[0] * axisU[0] + c0[2] * axisU[2];
  return {
    normal,
    axisU,
    origin: [
      c0[0] + (minU - u0) * axisU[0],
      minY,
      c0[2] + (minU - u0) * axisU[2],
    ],
    widthM,
    heightM,
  };
}

/**
 * An opening's world-space quad from its normalized rect_uv, wound to
 * front the interior, optionally floated off the wall along the interior
 * normal (the inset-patch z-fight offset).
 */
export function openingRect(
  frame: WallFrame,
  rectUv: [[number, number], [number, number]],
  offsetM = 0,
): [Vec3, Vec3, Vec3, Vec3] {
  const [[u0, v0], [u1, v1]] = rectUv;
  const at = (u: number, v: number): Vec3 => [
    frame.origin[0] + u * frame.widthM * frame.axisU[0] + offsetM * frame.normal[0],
    frame.origin[1] + v * frame.heightM,
    frame.origin[2] + u * frame.widthM * frame.axisU[2] + offsetM * frame.normal[2],
  ];
  return [at(u0, v0), at(u1, v0), at(u1, v1), at(u0, v1)];
}

/**
 * The polygon's corners as 2D (u, v) coordinates in the wall frame —
 * triangulation input. Interior-fronting winding projects to
 * counter-clockwise 2D, with the bounding box spanning
 * [0, widthM] x [0, heightM].
 */
export function projectToWallPlane(
  corners: Vec3[],
  frame: WallFrame,
): [number, number][] {
  return corners.map((c) => [
    (c[0] - frame.origin[0]) * frame.axisU[0] +
      (c[2] - frame.origin[2]) * frame.axisU[2],
    c[1] - frame.origin[1],
  ]);
}
