/**
 * The room, reduced to what a card can honestly draw: a floor contour, the
 * walls standing on it, their openings, and three numbers. Meters and world
 * XZ throughout — nothing here knows the card exists, and nothing here is
 * in pixels.
 *
 * WHAT MAKES THIS "MEASURED". A shell carries two geometries side by side,
 * and the distinction is load-bearing (0069): `polygon`/`quad` is what the
 * viewer RENDERS, after closure has extended a wall to meet its neighbour
 * or dropped it to the floor; `measured_polygon`/`measured_quad` is what
 * was DETECTED. On the roomplan method the two are the same object —
 * CapturedRoom geometry verbatim — which is why the product's own path
 * loses nothing here. Where they differ, this module draws and dimensions
 * the MEASURED extent, because a card is a picture of a measurement and a
 * closure-extended wall is not one.
 *
 * That choice creates one problem and solves it exactly. An opening's
 * `rect_uv` is normalized against the RENDERED polygon's in-plane bounding
 * rect (lib/shell3d.ts mirrors the server frame), so a fraction taken from
 * the rendered wall cannot be replayed against a shorter measured wall. So
 * openings are resolved to their world position in the rendered frame and
 * then expressed against the measured segment, on the shared u-axis both
 * frames project onto. An opening that falls outside the measured extent
 * is clipped away rather than moved: we did not measure that piece of wall.
 *
 * Consumers: lib/card/layout.ts (the only one). Tests pin the tolerance
 * this module reproduces against the hand-authored precedent in
 * docs/product/og-card.html.
 */

import type {
  SceneManifest,
  ShellDoc,
  ShellWallEntry,
  ShellWallEntryV3,
} from "@/lib/api/types";
import { wallFrame, type Vec3 } from "@/lib/shell3d";

/** A point on the plan: world meters, the XZ plane seen from above. */
export interface Pt2 {
  x: number;
  z: number;
}

export type OpeningKind = "window" | "door" | "opening";

/** One opening, as a span of the wall segment it sits in. */
export interface PlanOpening {
  kind: OpeningKind;
  /** Fractions along a -> b, 0 <= t0 < t1 <= 1. */
  t0: number;
  t1: number;
}

/** One wall, as it stands on the plan. */
export interface WallPlan {
  wallId: string;
  a: Pt2;
  b: Pt2;
  lengthM: number;
  /** Measured height (max y - min y of the detected extent), or null. */
  heightM: number | null;
  /** Unit XZ normal pointing OUT of the room — dimension lines go here. */
  outward: Pt2;
  openings: PlanOpening[];
}

export interface RoomMeasure {
  /** The measured floor boundary, world XZ, in polygon order. */
  contour: Pt2[];
  floorAreaM2: number;
  walls: WallPlan[];
  /**
   * The tallest measured wall. A measured wall height is a lower bound on
   * the ceiling — you only measure what the scan saw — so the tallest is
   * the best-supported reading and never overstates.
   */
  ceilingM: number | null;
  /** The floor's measured dominant colour; null = unobserved (0069's
   * neutral treatment: never a fabricated colour). */
  floorAlbedoHex: string | null;
  /** Objects perception placed. Deliberately a COUNT and never a list:
   * an inventory of a person's furniture is rung 2 (0208), not this. */
  pieceCount: number;
  /** The wall the card dimensions: the longest measured one. */
  datum: WallPlan | null;
}

const EPS = 1e-9;

function xz(c: Vec3): Pt2 {
  return { x: c[0], z: c[2] };
}

/** Twice the signed area of a closed XZ polygon (shoelace). */
function shoelace2(points: Pt2[]): number {
  let acc = 0;
  for (let i = 0; i < points.length; i++) {
    const p = points[i];
    const q = points[(i + 1) % points.length];
    acc += p.x * q.z - q.x * p.z;
  }
  return acc;
}

/** The corners a wall RENDERS with — v3 polygons, v2 quads. */
function renderedCorners(wall: ShellWallEntry | ShellWallEntryV3): Vec3[] {
  return ("polygon" in wall ? wall.polygon : wall.quad) as Vec3[];
}

/**
 * The corners a wall was DETECTED with, or null when the shell declares
 * none — in which case what it renders is what it measured (the roomplan
 * method's contract).
 */
function measuredCorners(wall: ShellWallEntry | ShellWallEntryV3): Vec3[] | null {
  const v3 = wall as ShellWallEntryV3;
  if (v3.measured_polygon && v3.measured_polygon.length >= 3) {
    return v3.measured_polygon as Vec3[];
  }
  if (v3.measured_quad && v3.measured_quad.length >= 3) {
    return v3.measured_quad as Vec3[];
  }
  const v2 = wall as ShellWallEntry;
  if (v2.measured_quad && v2.measured_quad.length >= 3) {
    return v2.measured_quad as Vec3[];
  }
  return null;
}

function openingKind(classification: string | null | undefined): OpeningKind {
  const c = String(classification ?? "").toLowerCase();
  return c === "window" || c === "door" ? c : "opening";
}

/** Extent of `corners` along a unit XZ axis, and along world Y. */
function extents(corners: Vec3[], ax: number, az: number) {
  let minU = Infinity;
  let maxU = -Infinity;
  let minY = Infinity;
  let maxY = -Infinity;
  for (const c of corners) {
    const u = c[0] * ax + c[2] * az;
    if (u < minU) minU = u;
    if (u > maxU) maxU = u;
    if (c[1] < minY) minY = c[1];
    if (c[1] > maxY) maxY = c[1];
  }
  return { minU, maxU, minY, maxY };
}

/** One wall's plan segment, or null when its geometry is degenerate. */
function wallToPlan(wall: ShellWallEntry | ShellWallEntryV3): WallPlan | null {
  const rendered = renderedCorners(wall);
  if (!rendered || rendered.length < 3) return null;
  // The UV frame openings are normalized against is the RENDERED one.
  const frame = wallFrame(rendered);
  if (!frame) return null;
  const [ax, , az] = frame.axisU;

  const measured = measuredCorners(wall) ?? rendered;
  const r = extents(rendered, ax, az);
  const m = extents(measured, ax, az);
  const lengthM = m.maxU - m.minU;
  if (!(lengthM > EPS)) return null;

  // Reconstruct world points on the MEASURED line from a scalar u. All
  // corners of a planar vertical wall share one perpendicular offset, so
  // one reference corner fixes it.
  const ref = measured[0];
  const refU = ref[0] * ax + ref[2] * az;
  const at = (u: number): Pt2 => ({
    x: ref[0] + (u - refU) * ax,
    z: ref[2] + (u - refU) * az,
  });

  const renderedSpan = r.maxU - r.minU;
  const openings: PlanOpening[] = [];
  for (const op of wall.openings ?? []) {
    const rect = op?.rect_uv;
    if (!rect || rect.length !== 2) continue;
    const [[u0], [u1]] = rect;
    if (!Number.isFinite(u0) || !Number.isFinite(u1)) continue;
    // Resolve to world position in the rendered frame, then express
    // against the measured segment; clip to what was actually measured.
    const lo = Math.min(u0, u1);
    const hi = Math.max(u0, u1);
    const worldLo = Math.max(r.minU + lo * renderedSpan, m.minU);
    const worldHi = Math.min(r.minU + hi * renderedSpan, m.maxU);
    if (worldHi - worldLo < 0.01) continue; // under a centimetre: not a hole
    openings.push({
      kind: openingKind(op.classification),
      t0: (worldLo - m.minU) / lengthM,
      t1: (worldHi - m.minU) / lengthM,
    });
  }

  const height = m.maxY - m.minY;
  return {
    wallId: wall.wall_id,
    a: at(m.minU),
    b: at(m.maxU),
    lengthM,
    heightM: height > EPS ? height : null,
    // frame.normal points INTO the room (the winding contract), so the
    // dimension side is its negation.
    outward: { x: -frame.normal[0], z: -frame.normal[2] },
    openings,
  };
}

/**
 * Reduce a shell and manifest to the card's subject, or null when there is
 * no measured floor to draw. A room with no contour gets no card — there
 * is nothing to make a picture of, and inventing one is the failure mode
 * this whole module is shaped to avoid.
 */
export function measureRoom(
  shell: ShellDoc | null | undefined,
  manifest: SceneManifest | null | undefined,
): RoomMeasure | null {
  if (!shell || shell.status !== "ready" || !shell.floor) return null;
  const floor = shell.floor;
  const source =
    (floor.measured_polygon && floor.measured_polygon.length >= 3
      ? floor.measured_polygon
      : floor.polygon) ?? [];
  if (source.length < 3) return null;
  const contour = (source as Vec3[]).map(xz);
  const floorAreaM2 = Math.abs(shoelace2(contour)) / 2;
  if (!(floorAreaM2 > EPS)) return null;

  const walls: WallPlan[] = [];
  for (const wall of shell.walls ?? []) {
    const plan = wallToPlan(wall);
    if (plan) walls.push(plan);
  }

  let ceilingM: number | null = null;
  for (const w of walls) {
    if (w.heightM !== null && (ceilingM === null || w.heightM > ceilingM)) {
      ceilingM = w.heightM;
    }
  }

  let datum: WallPlan | null = null;
  for (const w of walls) {
    if (datum === null || w.lengthM > datum.lengthM) datum = w;
  }

  const pieceCount = (manifest?.objects ?? []).filter(
    (o) => o?.placed === true,
  ).length;

  return {
    contour,
    floorAreaM2,
    walls,
    ceilingM,
    floorAlbedoHex: floor.material?.albedo_hex ?? null,
    pieceCount,
    datum,
  };
}
