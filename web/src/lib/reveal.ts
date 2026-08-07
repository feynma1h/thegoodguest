/**
 * The reveal's choreography — as a table, not as code buried in a render
 * loop (decision 0097).
 *
 * The reveal is the product's defining moment, and the first time it was
 * watched at real speed (RP-8, decision 0080) the verdict was that pieces
 * "come down at high speed then slow as a spring" and that walls and floor
 * should MATERIALIZE IN PLACE rather than arrive. This module is the
 * redesign's decision layer: every "what moves, when, for how long, and
 * whether the guest names it" answer lives here as a pure function, so the
 * choreography is reviewable as a table and testable without a browser.
 * SplatViewer PLAYS this plan; it does not decide it.
 *
 * The shape, in four movements:
 *
 *   1. The outline. The room's boundary draws itself on the dark stage —
 *      the measured floor perimeter traced by a moving pen, then verticals
 *      rising at each corner, then the top edge closing the box. No
 *      surface exists yet. The room's EXTENT is established before any
 *      material, so surfaces later appear inside a boundary the eye has
 *      already accepted, and nothing ever has to fly in from off-stage.
 *      This is the honest register too: the contour is the measurement —
 *      the thing the capture actually produced.
 *   2. The surfaces materialize. Floor, then walls, fading up IN PLACE
 *      (zero translation), swept around the room in the contour's own
 *      rotational direction. The contour dims away underneath them: the
 *      measurement handing off to the material.
 *   3. The pieces settle. No drop. Each object fades up while easing down
 *      a few centimetres on a curve that begins AND ends at zero velocity
 *      — it starts at rest and arrives at rest, which is what "settle"
 *      means and is the exact opposite of the ease-out cubic that earned
 *      the RP-8 note. The first pieces are introduced one at a time and
 *      named; the rest arrive as one quickening wave, unnamed, so the
 *      assembly finishes as a breath instead of a queue.
 *   4. A beat of quiet before the guest speaks.
 *
 * ONE easing curve governs everything that moves, echoing the single-spring
 * rule the DOM motion system already follows (components/ui/spring.tsx).
 *
 * Reduced motion collapses to the finished room on the first frame: no
 * contour, no fades, no captions — nothing pretends to have materialized.
 */

import type { PositionedSplat, ShellPlane } from "@/lib/api/types";

export type Vec3 = [number, number, number];

/* ------------------------------------------------------------------ *
 * Motion vocabulary
 * ------------------------------------------------------------------ */

/**
 * Smootherstep (6t⁵ − 15t⁴ + 10t³): zero velocity AND zero acceleration at
 * both ends. Everything in the reveal moves on this one curve — the pen
 * tracing the boundary, the surfaces fading up, the pieces settling.
 *
 * This is the redesign's load-bearing choice. The old drop used
 * 1 − (1 − t)³, whose velocity is MAXIMAL at t = 0: motion that begins at
 * full speed and brakes. Starting and ending at rest is what reads as
 * settling rather than landing.
 */
export function settleEase(t: number): number {
  const x = t <= 0 ? 0 : t >= 1 ? 1 : t;
  return x * x * x * (x * (x * 6 - 15) + 10);
}

/** Progress of a [startMs, startMs+durationMs] window at time `nowMs`,
 * clamped to [0, 1]. A zero/negative duration reads as instantly done. */
export function windowProgress(
  nowMs: number,
  startMs: number,
  durationMs: number,
): number {
  // Duration first: an instant cue (the reduced-motion plan is all of
  // them) must read as DONE on the frame it starts, not as not-started.
  if (durationMs <= 0) return nowMs >= startMs ? 1 : 0;
  if (nowMs <= startMs) return 0;
  return Math.min(1, (nowMs - startMs) / durationMs);
}

/* ------------------------------------------------------------------ *
 * Timing constants — the score
 * ------------------------------------------------------------------ */

/** A beat of black before the room starts measuring itself. */
export const CONTOUR_START_MS = 260;
/** The floor perimeter traces, at the pen's pace. */
export const CONTOUR_DRAW_MS = 1250;
/** Verticals begin before the floor loop closes — the movements overlap so
 * the reveal flows rather than proceeding in steps. */
export const RISER_START_MS = 950;
export const RISER_DRAW_MS = 620;
export const TOP_START_MS = 1320;
export const TOP_DRAW_MS = 760;
/** The measurement dims out once its surface has arrived. */
export const CONTOUR_FADE_MS = 700;

/** The floor materializes while the top edge is still drawing. */
export const FLOOR_SURFACE_START_MS = 1600;
export const SURFACE_FADE_MS = 760;
/** Walls follow the floor, swept around the room one step apart. */
export const WALL_LEAD_MS = 180;
export const WALL_STEP_MS = 130;

/** Objects wait for the last wall to FINISH — no object ever fades against
 * a half-transparent wall, which keeps splat/mesh compositing in the
 * configuration decision 0066's depth probe proved. */
export const OBJECT_LEAD_MS = 340;
/** With no shell there is no stage to build; the pieces come almost at
 * once. */
export const NO_SHELL_LEAD_MS = 420;
/** Introductions: one piece at a time, at a speaking pace. */
export const NAMED_STEP_MS = 780;
/** Then the rest, as a wave. */
export const WAVE_STEP_MS = 155;
/** One piece's settle, rest to rest. */
export const SETTLE_MS = 900;
/** How far a piece eases down into place. A whisper — the old value was
 * 0.40 m, which reads as a fall. */
export const SETTLE_DROP_M = 0.06;
/** A piece is fully present before it stops moving, so the last of the
 * motion is a whisper rather than a landing. */
export const SETTLE_FADE_FRACTION = 0.7;
/** How many pieces the guest introduces by name before the wave. */
export const NAMED_MAX = 3;
/** Rooms this small get every piece named — a 3-named + 1-wave split would
 * read as an accident. */
export const NAMED_ALL_UNDER = 6;
/** How long the last name stays up once the wave has taken over. */
export const CAPTION_DWELL_MS = 1400;
/** The room is quiet for a beat before the guest speaks. */
export const DONE_BEAT_MS = 450;

/* ------------------------------------------------------------------ *
 * Path math (pure; no renderer types cross this boundary)
 * ------------------------------------------------------------------ */

/** Cumulative arc length at each vertex of a polyline (first entry 0). */
export function pathLengths(path: Vec3[]): number[] {
  const out = [0];
  for (let i = 1; i < path.length; i++) {
    const [ax, ay, az] = path[i - 1];
    const [bx, by, bz] = path[i];
    out.push(out[i - 1] + Math.hypot(bx - ax, by - ay, bz - az));
  }
  return out;
}

/**
 * The point at arc length `s` along a polyline, plus the index of the
 * vertex it has passed. Clamped at both ends. Used both for the pen's tip
 * (an exact fractional position, so the growing line never steps) and for
 * the dots riding behind it.
 */
export function pathPointAt(
  path: Vec3[],
  lengths: number[],
  s: number,
): { point: Vec3; segment: number } {
  const total = lengths[lengths.length - 1];
  if (path.length === 0) return { point: [0, 0, 0], segment: 0 };
  if (path.length === 1 || total <= 0) return { point: path[0], segment: 0 };
  const clamped = Math.max(0, Math.min(total, s));
  let i = 1;
  while (i < lengths.length - 1 && lengths[i] < clamped) i++;
  const segStart = lengths[i - 1];
  const segLen = lengths[i] - segStart;
  const t = segLen <= 0 ? 0 : (clamped - segStart) / segLen;
  const [ax, ay, az] = path[i - 1];
  const [bx, by, bz] = path[i];
  return {
    point: [ax + (bx - ax) * t, ay + (by - ay) * t, az + (bz - az) * t],
    segment: i - 1,
  };
}

/* ------------------------------------------------------------------ *
 * Contour geometry
 * ------------------------------------------------------------------ */

export interface ContourGeometry {
  /** The measured floor perimeter, closed (last point repeats the first). */
  loop: Vec3[];
  /** The same loop at the walls' top height, or null with no walls. */
  topLoop: Vec3[] | null;
  /** Vertical edges at each floor corner, or empty with no walls. */
  risers: { from: Vec3; to: Vec3 }[];
  /** +1 if the floor polygon winds counter-clockwise in XZ, else −1. Walls
   * sweep in this same rotational sense so the fill follows the pen. */
  winding: 1 | -1;
}

/**
 * The room's boundary, derived from the measured shell alone: the floor
 * polygon's perimeter, and — if walls were measured — verticals at each
 * corner up to the highest wall point and a matching top loop.
 *
 * Returns null when there is no floor polygon to trace. Nothing is
 * invented: with no measured floor there is no boundary to draw, and the
 * reveal simply proceeds to whatever surfaces exist.
 */
export function contourGeometry(shell: ShellPlane[]): ContourGeometry | null {
  const floor = shell.find((p) => p.kind === "floor" && p.corners.length >= 3);
  if (!floor) return null;
  const corners = floor.corners as Vec3[];
  const loop: Vec3[] = [...corners, corners[0]];

  // Signed area in XZ gives the winding the pen will travel.
  let area2 = 0;
  for (let i = 0; i < corners.length; i++) {
    const [ax, , az] = corners[i];
    const [bx, , bz] = corners[(i + 1) % corners.length];
    area2 += ax * bz - bx * az;
  }
  const winding: 1 | -1 = area2 >= 0 ? 1 : -1;

  const wallYs = shell
    .filter((p) => p.kind === "wall")
    .flatMap((p) => p.corners.map((c) => c[1]));
  if (wallYs.length === 0) {
    return { loop, topLoop: null, risers: [], winding };
  }
  const topY = Math.max(...wallYs);
  const risers = corners
    .filter((c) => topY - c[1] > 1e-3)
    .map((c) => ({ from: c, to: [c[0], topY, c[2]] as Vec3 }));
  const topLoop = loop.map((c) => [c[0], topY, c[2]] as Vec3);
  return { loop, topLoop, risers, winding };
}

/* ------------------------------------------------------------------ *
 * The plan
 * ------------------------------------------------------------------ */

export interface SurfaceCue {
  /** Index into the shell array as given. */
  index: number;
  startMs: number;
  durationMs: number;
}

export interface ObjectCue {
  /** Index into the splats array as given. */
  index: number;
  /** Arrival order, largest piece first. */
  seq: number;
  startMs: number;
  durationMs: number;
  /** Whether the guest names this one aloud. */
  named: boolean;
}

export interface RevealPlan {
  /** Null when reduced motion is on, or when no floor was measured. */
  contour:
    | (ContourGeometry & {
        startMs: number;
        drawMs: number;
        riserStartMs: number;
        riserDrawMs: number;
        topStartMs: number;
        topDrawMs: number;
        fadeStartMs: number;
        fadeMs: number;
      })
    | null;
  surfaces: SurfaceCue[];
  objects: ObjectCue[];
  /** When the last named caption should leave the screen. */
  captionsDoneMs: number;
  /** When the room is assembled and quiet — the guest speaks here. */
  doneMs: number;
  /** True when the plan is a single frame: reduced motion, or nothing to
   * animate. Everything is visible at t = 0 and doneMs is 0. */
  immediate: boolean;
}

/** A splat's size proxy — uniform scale, or the largest axis of the staged
 * per-axis A/B variant (PositionedSplat.scale). */
export function splatSize(scale: number | [number, number, number]): number {
  return typeof scale === "number" ? scale : Math.max(...scale);
}

/** How many of the arriving pieces the guest introduces by name. */
export function namedCount(total: number): number {
  if (total <= 0) return 0;
  return total < NAMED_ALL_UNDER ? total : NAMED_MAX;
}

/**
 * Walls in the order they fill in: swept around the room from the pen's
 * starting corner, in the contour's own rotational direction. Array order
 * would read as a shuffle; this reads as a sweep.
 *
 * Returns indices into `shell`. Non-wall planes are excluded.
 */
export function wallSweepOrder(
  shell: ShellPlane[],
  contour: ContourGeometry | null,
): number[] {
  const walls = shell
    .map((p, index) => ({ p, index }))
    .filter((e) => e.p.kind === "wall" && e.p.corners.length > 0);
  if (!contour) return walls.map((e) => e.index);

  // Sweep around the floor's own centroid, starting at the pen's corner.
  const ring = contour.loop.slice(0, -1);
  const cx = ring.reduce((a, c) => a + c[0], 0) / ring.length;
  const cz = ring.reduce((a, c) => a + c[2], 0) / ring.length;
  const start = Math.atan2(ring[0][2] - cz, ring[0][0] - cx);
  const key = (e: { p: ShellPlane }) => {
    const n = e.p.corners.length;
    const wx = e.p.corners.reduce((a, c) => a + c[0], 0) / n;
    const wz = e.p.corners.reduce((a, c) => a + c[2], 0) / n;
    const d = (Math.atan2(wz - cz, wx - cx) - start) * contour.winding;
    // Into [0, 2π) so the sweep completes exactly one lap.
    return ((d % (2 * Math.PI)) + 2 * Math.PI) % (2 * Math.PI);
  };
  return walls
    .map((e) => ({ index: e.index, k: key(e) }))
    .sort((a, b) => a.k - b.k || a.index - b.index)
    .map((e) => e.index);
}

/**
 * The whole reveal, as a table of cues.
 *
 * `shell` and `splats` are the same arrays SplatViewer renders, so every
 * cue's `index` addresses them directly.
 */
export function planReveal({
  shell,
  splats,
  reducedMotion = false,
}: {
  shell: ShellPlane[];
  splats: Pick<PositionedSplat, "scale">[];
  reducedMotion?: boolean;
}): RevealPlan {
  const nothingToPlay = shell.length === 0 && splats.length === 0;
  if (reducedMotion || nothingToPlay) {
    return {
      contour: null,
      surfaces: shell.map((_, index) => ({
        index,
        startMs: 0,
        durationMs: 0,
      })),
      objects: splats.map((_, index) => ({
        index,
        seq: index,
        startMs: 0,
        durationMs: 0,
        named: false,
      })),
      captionsDoneMs: 0,
      doneMs: 0,
      immediate: true,
    };
  }

  const geom = contourGeometry(shell);
  const floorIndex = shell.findIndex((p) => p.kind === "floor");
  const wallOrder = wallSweepOrder(shell, geom);

  const surfaces: SurfaceCue[] = [];
  let surfacesEndMs = 0;
  if (floorIndex >= 0) {
    surfaces.push({
      index: floorIndex,
      startMs: FLOOR_SURFACE_START_MS,
      durationMs: SURFACE_FADE_MS,
    });
    surfacesEndMs = FLOOR_SURFACE_START_MS + SURFACE_FADE_MS;
  }
  const wallBase =
    (floorIndex >= 0 ? FLOOR_SURFACE_START_MS + WALL_LEAD_MS : CONTOUR_START_MS);
  wallOrder.forEach((index, i) => {
    const startMs = wallBase + i * WALL_STEP_MS;
    surfaces.push({ index, startMs, durationMs: SURFACE_FADE_MS });
    surfacesEndMs = Math.max(surfacesEndMs, startMs + SURFACE_FADE_MS);
  });
  // Any plane that is neither the floor nor a wall still materializes,
  // rather than silently never appearing.
  shell.forEach((p, index) => {
    if (index === floorIndex || wallOrder.includes(index)) return;
    surfaces.push({ index, startMs: wallBase, durationMs: SURFACE_FADE_MS });
    surfacesEndMs = Math.max(surfacesEndMs, wallBase + SURFACE_FADE_MS);
  });

  const objectsBaseMs =
    surfaces.length > 0 ? surfacesEndMs + OBJECT_LEAD_MS : NO_SHELL_LEAD_MS;
  const named = namedCount(splats.length);

  const order = splats
    .map((s, index) => ({ index, size: splatSize(s.scale) }))
    .sort((a, b) => b.size - a.size || a.index - b.index);

  const objects: ObjectCue[] = [];
  let cursor = objectsBaseMs;
  let lastNamedStartMs = objectsBaseMs;
  order.forEach((entry, seq) => {
    if (seq > 0) cursor += seq <= named ? NAMED_STEP_MS : WAVE_STEP_MS;
    const isNamed = seq < named;
    if (isNamed) lastNamedStartMs = cursor;
    objects.push({
      index: entry.index,
      seq,
      startMs: cursor,
      durationMs: SETTLE_MS,
      named: isNamed,
    });
  });

  const lastMotionMs = objects.length
    ? cursor + SETTLE_MS
    : surfaces.length
      ? surfacesEndMs
      : 0;

  return {
    contour: geom
      ? {
          ...geom,
          startMs: CONTOUR_START_MS,
          drawMs: CONTOUR_DRAW_MS,
          riserStartMs: RISER_START_MS,
          riserDrawMs: RISER_DRAW_MS,
          topStartMs: TOP_START_MS,
          topDrawMs: TOP_DRAW_MS,
          fadeStartMs: surfacesEndMs,
          fadeMs: CONTOUR_FADE_MS,
        }
      : null,
    surfaces,
    objects,
    captionsDoneMs: named > 0 ? lastNamedStartMs + CAPTION_DWELL_MS : 0,
    doneMs: lastMotionMs + DONE_BEAT_MS,
    immediate: false,
  };
}
