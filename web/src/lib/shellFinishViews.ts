/**
 * The diorama's fixed viewpoints (local finish override). Instead of free
 * orbit, the room is seen from a handful of settled corner views — the
 * symmetric isometric look of the reference — chosen by scoring each corner
 * of the room. Pure math here; the camera rig that animates between them is
 * components/shellFinishViewRig.ts.
 *
 * A view looks into one corner (two adjacent walls kept, the other two cut
 * away). It is scored by what the kept walls hold (area, window, door) and
 * penalised for furniture hidden behind other furniture from that side,
 * because a tall bookcase between the camera and the bed makes the bed
 * unreadable from one corner while another corner shows both.
 */

import { chooseCutaway, wallAdjacency, type CutawayWall } from "@/lib/shellFinish";
import type { Vec3 } from "@/lib/shell3d";

/** An oriented, yaw-only box in world space (RoomPlan / splat clip shape). */
export interface WorldBox {
  center: Vec3;
  half: Vec3;
  yaw: number;
}

export interface ViewPreset {
  /** The two kept walls (indices into the wall list). */
  keep: [number, number];
  /** OrbitControls azimuth (radians; 0 = camera on +Z, increasing toward +X). */
  azimuth: number;
  /** Camera elevation above the horizon, radians. */
  elevation: number;
  /** Higher is a better view. */
  score: number;
  /** Furniture pieces substantially hidden from this side. */
  hidden: number;
}

/** Camera elevation. The reference diorama's wall edges slope ~19 degrees,
 * which for a 45-degree view is an elevation near 20; the textbook isometric
 * 35 degrees reads as looking down from on high. 24 keeps a little more floor. */
export const ISO_ELEVATION_RAD = (24 * Math.PI) / 180;

/** The 8 corners of a box, rotated about Y. */
function boxCorners(b: WorldBox): Vec3[] {
  const c = Math.cos(b.yaw);
  const s = Math.sin(b.yaw);
  const out: Vec3[] = [];
  for (const sx of [-1, 1]) {
    for (const sy of [-1, 1]) {
      for (const sz of [-1, 1]) {
        const x = sx * b.half[0];
        const z = sz * b.half[2];
        out.push([b.center[0] + x * c + z * s, b.center[1] + sy * b.half[1], b.center[2] - x * s + z * c]);
      }
    }
  }
  return out;
}

/** Furniture pieces (as indices) whose projected silhouette is mostly covered
 * by a closer, taller box, seen from the given azimuth/elevation. A cheap
 * rectangle test on the screen-space bounds — enough to tell a view that
 * shows the bed from one that hides it behind a cupboard. */
export function hiddenPieces(boxes: WorldBox[], azimuth: number, elevation: number): number[] {
  // Camera basis: forward points from the camera toward the scene.
  const f: Vec3 = [
    -Math.sin(azimuth) * Math.cos(elevation),
    -Math.sin(elevation),
    -Math.cos(azimuth) * Math.cos(elevation),
  ];
  const right: Vec3 = [Math.cos(azimuth), 0, -Math.sin(azimuth)];
  const up: Vec3 = [
    right[1] * f[2] - right[2] * f[1],
    right[2] * f[0] - right[0] * f[2],
    right[0] * f[1] - right[1] * f[0],
  ];
  const dot = (a: Vec3, b: Vec3) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
  const info = boxes.map((b) => {
    const pts = boxCorners(b).map((p) => [dot(p, right), dot(p, up)] as [number, number]);
    const xs = pts.map((p) => p[0]);
    const ys = pts.map((p) => p[1]);
    return {
      r: [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)] as [number, number, number, number],
      // Depth toward the camera: larger = closer (forward points away from it).
      near: -dot(b.center, f),
      top: b.center[1] + b.half[1],
    };
  });
  const area = (r: number[]) => Math.max(0, r[2] - r[0]) * Math.max(0, r[3] - r[1]);
  const hidden: number[] = [];
  info.forEach((a, i) => {
    const a0 = area(a.r);
    if (a0 < 1e-6) return;
    let covered = 0;
    info.forEach((b, j) => {
      if (i === j || b.near <= a.near + 0.15 || b.top < a.top - 0.05) return; // must be closer and not shorter
      const w = Math.min(a.r[2], b.r[2]) - Math.max(a.r[0], b.r[0]);
      const h = Math.min(a.r[3], b.r[3]) - Math.max(a.r[1], b.r[1]);
      if (w > 0 && h > 0) covered = Math.max(covered, (w * h) / a0);
    });
    if (covered > 0.4) hidden.push(i);
  });
  return hidden;
}

/**
 * Up to `max` views, best first: every corner of the room scored, hidden
 * furniture subtracted. Walls that do not form a corner (opposite pairs) are
 * never a view.
 */
export function planViews(
  walls: CutawayWall[],
  boxes: WorldBox[] = [],
  max = 4,
  elevation = ISO_ELEVATION_RAD,
): ViewPreset[] {
  const views: ViewPreset[] = [];
  for (const pair of wallAdjacency(walls)) {
    const c = chooseCutaway(walls, pair);
    if (!c) continue;
    const hidden = hiddenPieces(boxes, c.azimuthRad, elevation);
    views.push({
      keep: pair,
      azimuth: c.azimuthRad,
      elevation,
      score: c.score - hidden.length * 3,
      hidden: hidden.length,
    });
  }
  return views.sort((a, b) => b.score - a.score).slice(0, max);
}

/** Floor position (x, z) of the first door in the wall list, or null. */
export function doorPosition(walls: CutawayWall[]): [number, number] | null {
  for (const w of walls) {
    const d = w.openings.find((o) => o.classification === "door" && o.rect_uv);
    if (!d || !d.rect_uv || w.corners.length < 2) continue;
    const u = (d.rect_uv[0][0] + d.rect_uv[1][0]) / 2;
    const a = w.corners[0];
    const b = w.corners[1];
    return [a[0] + (b[0] - a[0]) * u, a[2] + (b[2] - a[2]) * u];
  }
  return null;
}

/** The corner a view opens at: where its two cut-away walls meet (the front
 * corner nearest the camera), or null when the cut walls share none. */
export function openCorner(keep: [number, number], walls: CutawayWall[], tol = 0.06): [number, number] | null {
  const cut = walls.map((_, i) => i).filter((i) => i !== keep[0] && i !== keep[1]);
  for (let i = 0; i < cut.length; i++) {
    for (let j = i + 1; j < cut.length; j++) {
      for (const a of walls[cut[i]].corners) {
        for (const b of walls[cut[j]].corners) {
          if (Math.hypot(a[0] - b[0], a[2] - b[2]) < tol) return [(a[0] + b[0]) / 2, (a[2] + b[2]) / 2];
        }
      }
    }
  }
  return null;
}

/** Put first the view that opens at the corner nearest the door, so the room
 * opens where a person would walk in. Unchanged when the room has no door. */
export function openAtDoor(views: ViewPreset[], walls: CutawayWall[]): ViewPreset[] {
  const door = doorPosition(walls);
  if (!door || views.length < 2) return views;
  let best = -1;
  let bestD = Infinity;
  views.forEach((v, i) => {
    const c = openCorner(v.keep, walls);
    if (!c) return;
    const d = Math.hypot(c[0] - door[0], c[1] - door[1]);
    if (d < bestD) {
      bestD = d;
      best = i;
    }
  });
  if (best <= 0) return views;
  return [views[best], ...views.filter((_, i) => i !== best)];
}

/** Views in the order a person steps through them: by azimuth, starting from
 * the best view and going around. */
export function stepOrder(views: ViewPreset[]): ViewPreset[] {
  if (views.length < 2) return views;
  const best = views[0];
  const rest = views.slice(1).sort(
    (a, b) => wrap(a.azimuth - best.azimuth) - wrap(b.azimuth - best.azimuth),
  );
  return [best, ...rest];
}

/** Angle wrapped into [0, 2pi). */
export function wrap(a: number): number {
  const t = Math.PI * 2;
  return ((a % t) + t) % t;
}

/** Shortest signed turn from `a` to `b`. */
export function shortestTurn(a: number, b: number): number {
  const d = wrap(b - a);
  return d > Math.PI ? d - Math.PI * 2 : d;
}

/** Where the room's view should aim, and how far back to stand so the whole
 * room (floor, walls and slab) fits at the given lens. */
export function frameRoom(
  floor: Vec3[],
  wallHeight: number,
  fovDeg: number,
  margin = 0.9,
): { target: Vec3; distance: number; radius: number } {
  const xs = floor.map((p) => p[0]);
  const zs = floor.map((p) => p[2]);
  const y0 = floor[0][1];
  const cx = (Math.min(...xs) + Math.max(...xs)) / 2;
  const cz = (Math.min(...zs) + Math.max(...zs)) / 2;
  const hx = (Math.max(...xs) - Math.min(...xs)) / 2;
  const hz = (Math.max(...zs) - Math.min(...zs)) / 2;
  // Sphere around the room box; the plinth hangs ~0.1 m below the floor.
  const radius = Math.hypot(hx, hz, wallHeight / 2 + 0.05);
  const target: Vec3 = [cx, y0 + wallHeight * 0.45, cz];
  const distance = (radius / Math.tan((fovDeg * Math.PI) / 360)) * margin;
  return { target, distance, radius };
}
