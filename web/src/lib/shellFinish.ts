/**
 * The LOCAL-ONLY shell finish: a small description (tools/shell_finish.py
 * writes it from shell.json + the scan's camera frames) of how to DRAW a
 * room's walls and floor in place of the flat measured polygons — paint
 * with a faint grain, soft corner shading, baseboards, framed door/window
 * openings, the floor drawn per its material family.
 *
 * It is not part of the serving contract and nothing here is fetched from
 * the backend: a developer points the viewer at a finish file on their own
 * machine (app/shell-finish). Colours are the measured ones, checked and
 * refined against the camera frames offline; trim dimensions and slab/plank
 * sizes are design choices the file marks `assumed`. No photo pixels travel
 * in it. Pure data + layout math; the three.js drawing is
 * components/shellFinishScene.ts, which SplatViewer calls.
 */

import { wallFrame, type Vec3, type WallFrame } from "@/lib/shell3d";

export interface FinishOpening {
  index: number;
  kind: string;
  /** Door leaf (or window fallback) colour, measured from the frames. */
  leaf_hex: string;
  /** Sash / frame colour measured inside the opening, when seen. */
  frame_hex?: string | null;
  /** Window glass, measured bright pixels, when seen. */
  glass_hex?: string | null;
  /** Casing drawn around the opening; null = none (the opening is cut
   * straight into the wall). */
  casing_hex?: string | null;
  /** Reviewed raised-panel layout on a door leaf: [u0, v0, u1, v1] in the
   * leaf's own 0..1 frame (v up). */
  panels?: [number, number, number, number][] | null;
  source: string;
}

/** A tiled band at the foot of a wall, topped by a border line. Tile pitch
 * is a reviewed value (null = no joints drawn, just the band). */
export interface FinishWainscot {
  height_m: number;
  tile_hex: string;
  joint_hex: string;
  border_hex: string;
  tile_u_m?: number | null;
  tile_v_m?: number | null;
}

export interface FinishWall {
  wall_id: string;
  paint: {
    hex: string;
    source: string;
    sheen: number;
    grain: number;
  };
  wainscot?: FinishWainscot | null;
  /** Null/absent = the wall meets the floor with no baseboard. */
  baseboard?: { hex: string; height_m: number } | null;
  openings: FinishOpening[];
}

export interface FinishFloorStyle {
  kind: string;
  mottle: number;
  speckle: number;
  seed: number;
  slab_u_m?: number;
  slab_v_m?: number;
  plank_w_m?: number;
  plank_dir_deg?: number | null;
}

export interface ShellFinish {
  finish_version: 2;
  scene_id: string | null;
  wall_count: number;
  trim: {
    hex: string;
    baseboard_h_m: number;
    baseboard_d_m: number;
    casing_w_m: number;
    casing_d_m: number;
  };
  walls: FinishWall[];
  floor: {
    hex: string;
    family: string | null;
    style: FinishFloorStyle;
  } | null;
  /** Colour gain applied to the finish materials (the viewer's light rig
   * darkens diffuse surfaces; this is the one calibration knob). Optional
   * in the file; the viewer defaults it. */
  exposure?: number;
  /** Diorama staging overrides (optional; the derivation does not write them). */
  staging?: {
    cap_hex?: string;
    wall_thickness_m?: number;
    keep?: [number, number];
    elevation_deg?: number;
  } | null;
}

const HEX = /^#[0-9a-fA-F]{6}$/;

/**
 * Validate a parsed finish file against the shell it is about to dress.
 * Returns null for anything that does not fit — wrong version, a wall count
 * that disagrees with the shell (a stale finish from another scan), a bad
 * colour — so a mismatched file draws nothing rather than a wrong room.
 */
export function parseFinish(raw: unknown, wallCount: number): ShellFinish | null {
  if (!raw || typeof raw !== "object") return null;
  const f = raw as Partial<ShellFinish>;
  if (f.finish_version !== 2) return null;
  if (f.wall_count !== wallCount || !Array.isArray(f.walls)) return null;
  if (f.walls.length !== wallCount) return null;
  const t = f.trim;
  if (!t || !HEX.test(t.hex)) return null;
  for (const n of [t.baseboard_h_m, t.baseboard_d_m, t.casing_w_m, t.casing_d_m]) {
    if (typeof n !== "number" || !(n >= 0 && n < 0.5)) return null;
  }
  for (const w of f.walls) {
    if (!w?.paint || !HEX.test(w.paint.hex)) return null;
    for (const o of w.openings ?? []) if (!HEX.test(o.leaf_hex)) return null;
    const wn = w.wainscot;
    if (wn && !(HEX.test(wn.tile_hex) && HEX.test(wn.joint_hex) && HEX.test(wn.border_hex) && wn.height_m > 0 && wn.height_m < 3)) return null;
    if (w.baseboard && !HEX.test(w.baseboard.hex)) return null;
  }
  if (f.floor) {
    if (!HEX.test(f.floor.hex) || !f.floor.style) return null;
  }
  return f as ShellFinish;
}

/** A stable signature so the viewer rebuilds when (and only when) the
 * finish changes. */
export function finishSignature(f: ShellFinish | null | undefined): string {
  return f ? JSON.stringify([f.scene_id, f.trim, f.walls, f.floor, f.exposure]) : "";
}

// ---------------------------------------------------------------- layout --

export interface MetricRect {
  u0: number;
  u1: number;
  v0: number;
  v1: number;
}

/** An opening's rect in metres on the wall's own plane (u along axisU from
 * the bounding rect's left, v up from its bottom). */
export function openingMetres(
  frame: WallFrame,
  rectUv: [[number, number], [number, number]],
): MetricRect {
  const [[a, b], [c, d]] = rectUv;
  return {
    u0: Math.min(a, c) * frame.widthM,
    u1: Math.max(a, c) * frame.widthM,
    v0: Math.min(b, d) * frame.heightM,
    v1: Math.max(b, d) * frame.heightM,
  };
}

/** True when the polygon fills its bounding rect (a plain rectangular wall).
 * Baseboards are laid only on those: a gabled or cut-out wall's bottom edge
 * is not the rect's, and a baseboard floating off the real edge would be a
 * wrong-specific claim — such walls get paint, no trim. */
export function isRectangularWall(corners: Vec3[], frame: WallFrame): boolean {
  let area = 0;
  for (let i = 0; i < corners.length; i++) {
    const a = corners[i];
    const b = corners[(i + 1) % corners.length];
    const ax = (a[0] - frame.origin[0]) * frame.axisU[0] + (a[2] - frame.origin[2]) * frame.axisU[2];
    const bx = (b[0] - frame.origin[0]) * frame.axisU[0] + (b[2] - frame.origin[2]) * frame.axisU[2];
    area += ax * (b[1] - frame.origin[1]) - bx * (a[1] - frame.origin[1]);
  }
  return Math.abs(Math.abs(area) / 2 - frame.widthM * frame.heightM) <
    0.02 * frame.widthM * frame.heightM;
}

/**
 * The runs along a wall's foot where a baseboard is laid: the whole width
 * minus every opening that reaches the floor (a door), each widened by the
 * casing so the board stops at the door trim. Spans shorter than a hand
 * are dropped.
 */
export function baseboardSpans(
  widthM: number,
  openings: MetricRect[],
  casingW: number,
  floorTolM = 0.03,
): [number, number][] {
  const cuts = openings
    .filter((o) => o.v0 <= floorTolM)
    .map((o): [number, number] => [o.u0 - casingW, o.u1 + casingW])
    .sort((a, b) => a[0] - b[0]);
  const spans: [number, number][] = [];
  let at = 0;
  for (const [c0, c1] of cuts) {
    if (c0 > at) spans.push([at, Math.min(c0, widthM)]);
    at = Math.max(at, c1);
  }
  if (at < widthM) spans.push([at, widthM]);
  return spans.filter(([a, b]) => b - a > 0.08);
}

export interface CasingPiece {
  /** Centre and size in the wall plane, metres. */
  cu: number;
  cv: number;
  w: number;
  h: number;
  /** Extra depth off the wall (sills stand proud of the casing). */
  deeper: number;
}

/**
 * Casing around an opening: head + two sides, plus either nothing at the
 * foot (a door) or a sill (anything that stops above the floor). Every
 * piece is clamped to the wall's rect so trim never pokes past a corner
 * into the neighbouring wall.
 */
export function casingPieces(
  rect: MetricRect,
  wallW: number,
  wallH: number,
  casingW: number,
): CasingPiece[] {
  const out: CasingPiece[] = [];
  const clampU = (a: number, b: number): [number, number] => [Math.max(0, a), Math.min(wallW, b)];
  const add = (u0: number, u1: number, v0: number, v1: number, deeper = 0) => {
    const [a, b] = clampU(u0, u1);
    const c = Math.max(0, v0);
    const d = Math.min(wallH, v1);
    if (b - a < 1e-3 || d - c < 1e-3) return;
    out.push({ cu: (a + b) / 2, cv: (c + d) / 2, w: b - a, h: d - c, deeper });
  };
  const floorToFoot = rect.v0 <= 0.03;
  const footV = floorToFoot ? rect.v0 : rect.v0;
  // Head spans the full casing width; sides run from the foot to the head.
  add(rect.u0 - casingW, rect.u1 + casingW, rect.v1, rect.v1 + casingW);
  add(rect.u0 - casingW, rect.u0, footV, rect.v1);
  add(rect.u1, rect.u1 + casingW, footV, rect.v1);
  if (!floorToFoot) {
    // Sill: a shelf, wider than the casing, standing proud of it.
    add(rect.u0 - casingW * 1.3, rect.u1 + casingW * 1.3, rect.v0 - casingW * 0.5, rect.v0, 0.022);
  }
  return out;
}

/** Wall frames for the planes, used by both the drawer and the tests. */
export function frameFor(corners: Vec3[]): WallFrame | null {
  return wallFrame(corners);
}

/** The finish's colour gain. Calibrated in the browser against the camera
 * frames; see tools/shell_finish.py notes. */
export const DEFAULT_EXPOSURE = 0.82;

// ------------------------------------------------------------ the flag --

/**
 * The finish is a developer's local override, off unless the build says so
 * (NEXT_PUBLIC_SHELL_FINISH=1 — the app/shell-finish page sets it in dev).
 * A production build has the flag absent, so the hook points in the viewer
 * are inert and this path ships nothing.
 */
export function shellFinishEnabled(): boolean {
  return process.env.NEXT_PUBLIC_SHELL_FINISH === "1";
}


// ---------------------------------------------------------------- staging --

export interface CutawayWall {
  corners: Vec3[];
  /** rect_uv: the opening's [[u0, v0], [u1, v1]] as fractions of the wall (u from corners[0] toward corners[1]). */
  openings: { classification: string; rect_uv?: [[number, number], [number, number]] }[];
}

export interface Cutaway {
  /** The two walls kept as the back corner. */
  keep: [number, number];
  /** OrbitControls azimuth (radians, 0 = camera on +Z) that looks into it. */
  azimuthRad: number;
  score: number;
}

/** Pairs of walls that meet at a corner (a shared vertex, within `tol`). */
export function wallAdjacency(walls: { corners: Vec3[] }[], tol = 0.06): [number, number][] {
  const out: [number, number][] = [];
  for (let i = 0; i < walls.length; i++) {
    for (let j = i + 1; j < walls.length; j++) {
      const shared = walls[i].corners.some((a) =>
        walls[j].corners.some((b) => Math.hypot(a[0] - b[0], a[2] - b[2]) < tol),
      );
      if (shared) out.push([i, j]);
    }
  }
  return out;
}

/**
 * Which corner to keep as the diorama's back corner, and where the camera
 * sits to look into it. Kept walls are the ones the viewer sees from inside,
 * so the camera lies along the sum of their interior normals. Scored by
 * wall area plus bonuses for the openings that make the corner worth looking
 * at (a window most — it is where the light comes from — then a door).
 * `override` picks a pair by wall index (finish.staging.keep).
 */
export function chooseCutaway(
  walls: CutawayWall[],
  override?: [number, number] | null,
): Cutaway | null {
  const frames = walls.map((w) => wallFrame(w.corners));
  let best: Cutaway | null = null;
  const pairs = override ? [override] : wallAdjacency(walls);
  for (const [i, j] of pairs) {
    const fi = frames[i];
    const fj = frames[j];
    if (!fi || !fj) continue;
    const dx = fi.normal[0] + fj.normal[0];
    const dz = fi.normal[2] + fj.normal[2];
    if (Math.hypot(dx, dz) < 0.3) continue; // opposite walls: not a corner
    let score = (fi.widthM * fi.heightM + fj.widthM * fj.heightM) / 10;
    for (const k of [i, j]) {
      for (const o of walls[k].openings) {
        score += o.classification === "window" ? 6 : o.classification === "door" ? 1.5 : 1;
      }
    }
    if (!best || score > best.score) {
      best = { keep: [i, j], azimuthRad: Math.atan2(dx, dz), score };
    }
  }
  return best;
}
