/**
 * The card as a display list: a pure function from a measured room to an
 * ordered list of drawing operations in card pixels. Nothing here paints,
 * and nothing here knows what a canvas is — `paint.ts` walks this list, and
 * it is the only thing that does.
 *
 * The split is deliberate and is the same one `lib/reveal.ts` makes for the
 * reveal: the score is a pure function so it can be reasoned about and
 * pinned, and the player is dumb. Every claim the card makes — every
 * coordinate, every number, every string — is decided here, so
 * `layout.test.ts` can hold the whole artifact to the measurement without a
 * browser.
 *
 * THE PROJECTION IS A UNIFORM SIMILARITY. World XZ maps to card pixels as
 * one rotation, one scalar scale `s` and one translation — a plan seen from
 * above, the view direction -Y. No per-axis scale and no shear, so EVERY
 * length on the card is exactly `s` times its measured length by
 * construction rather than by care; the tolerance is float64 and nothing
 * else, and `layout.test.ts` checks it over every pair of contour vertices
 * rather than over a bounding box.
 *
 * The rotation lays the dimensioned wall flat — see `orientation` for why
 * that discards nothing. The precedent, `docs/product/og-card.html`, drew
 * its room unrotated at 82 px/m; `measure.test.ts` holds the world-space
 * geometry to it, which is the layer where the two are comparable.
 *
 * WHAT THE CARD MAY CARRY (social-layer.md §6.2): the measured contour, the
 * derived date title, and a dimension, a count and a measured colour. WHAT
 * IT MUST NOT: any object likeness, any user-authored text, any photograph,
 * any identifier that resolves to the account or the scene. The second list
 * is enforced by what this function is never given — it takes a
 * `RoomMeasure`, which holds no labels, no ids and no URLs — and pinned by
 * `layout.test.ts` over the finished list.
 */

import { alpha, PALETTE, type CardFontRole } from "./palette";
import type { Pt2, RoomMeasure, WallPlan } from "./measure";

/* ------------------------------------------------------------------ *
 * The display list
 * ------------------------------------------------------------------ */

export type XY = [number, number];

export interface TextOp {
  kind: "text";
  text: string;
  at: XY;
  role: CardFontRole;
  size: number;
  weight: number;
  italic: boolean;
  /** Letter spacing in em. */
  tracking: number;
  fill: string;
  align: "left" | "center" | "right";
  /** Degrees clockwise about `at`. */
  rotateDeg: number;
  /** Condense rather than overflow — the painter hands this to fillText. */
  maxWidth: number | null;
}

export type CardOp =
  | { kind: "rect"; at: XY; w: number; h: number; fill: string }
  | { kind: "fill"; points: XY[]; fill: string }
  | { kind: "stroke"; points: XY[]; closed: boolean; stroke: string; width: number }
  /** A radial wash, clipped to `clip`. Windows only: gold is a light
   * indicator and never ornament (0057). */
  | { kind: "glow"; at: XY; radius: number; color: string; clip: XY[] }
  /** The product mark, drawn from the generated geometry — never a copy of
   * its paths (0193). `size` is the box it fits in. */
  | { kind: "mark"; at: XY; size: number }
  | TextOp;

export interface CardLayout {
  width: number;
  height: number;
  ops: CardOp[];
  /** Everything the card asserts, kept beside the drawing so tests and the
   * download filename read the same values the ink does. */
  claims: {
    scalePxPerM: number;
    title: string;
    ceilingText: string | null;
    floorText: string;
    pieceText: string | null;
    /** The wall the dimension line calls out, and the length it prints. */
    datum: { wallId: string; lengthM: number; text: string } | null;
    floorAlbedoHex: string | null;
  };
}

export interface CardFrame {
  w: number;
  h: number;
}

/** The two frames. Landscape is the og-card's, and the aspect a link
 * preview will later want (social-layer.md §7). */
export const CARD_FRAMES = {
  landscape: { w: 1200, h: 630 },
  square: { w: 1080, h: 1080 },
} as const;

export type CardVariant = keyof typeof CARD_FRAMES;

/* ------------------------------------------------------------------ *
 * Numbers, said the way the guest says them
 * ------------------------------------------------------------------ */

/**
 * One decimal of meters, never more — `scene_facts._format_m`'s rule, and
 * the reason is the same here: RoomPlan does not measure to the
 * centimetre, so a second decimal is a claim the scan cannot support.
 * (The og-card prints "3.02 m"; it was placed by hand before this rule was
 * written down, and one decimal is the one the product speaks.)
 */
export function formatM(value: number): string {
  return `${value.toFixed(1)} m`;
}

function formatM2(value: number): string {
  return `${value.toFixed(1)} m²`;
}

/* ------------------------------------------------------------------ *
 * Plan geometry helpers — all in card pixels
 * ------------------------------------------------------------------ */

interface Projector {
  s: number;
  p: (pt: Pt2) => XY;
  /** Unit world direction -> unit screen direction, for normals and for
   * the angle a dimension label sits at. */
  d: (pt: Pt2) => XY;
}

/**
 * The plan's orientation, from the wall it dimensions.
 *
 * A capture's world yaw is whichever way the phone was pointing when the
 * scan started — ARKit gravity-aligns Y and takes the initial heading from
 * the device — so it is not a measurement and there is nothing to preserve
 * in it. Normalising it is the same kind of act as centring the drawing.
 *
 * The datum wall is laid horizontal with the room above it and its
 * dimension line below, which is the plan convention, and which also means
 * the printed length is always the right way up rather than reading
 * bottom-to-top on a room that happened to be scanned facing north.
 *
 * A rotation is part of the similarity, so every length still reproduces
 * at exactly one scale.
 */
function orientation(datum: WallPlan | null): { c: number; s: number } {
  if (!datum) return { c: 1, s: 0 };
  const dx = datum.b.x - datum.a.x;
  const dz = datum.b.z - datum.a.z;
  const n = Math.hypot(dx, dz);
  if (!(n > 1e-9)) return { c: 1, s: 0 };
  let c = dx / n;
  let sn = dz / n;
  // R = [[c, sn], [-sn, c]] sends the wall to +X and (-sn, c) to +Y. Flip
  // a half turn when that puts the outward normal at the top instead.
  const outY = -sn * datum.outward.x + c * datum.outward.z;
  if (outY < 0) {
    c = -c;
    sn = -sn;
  }
  return { c, s: sn };
}

function bounds(points: XY[]) {
  let minX = Infinity;
  let maxX = -Infinity;
  let minZ = Infinity;
  let maxZ = -Infinity;
  for (const [x, z] of points) {
    if (x < minX) minX = x;
    if (x > maxX) maxX = x;
    if (z < minZ) minZ = z;
    if (z > maxZ) maxZ = z;
  }
  return { minX, maxX, minZ, maxZ };
}

/**
 * Fit the room into `box`, keeping `inset` pixels clear on every side for
 * the dimension callout, which is measured in pixels rather than meters
 * and so cannot be part of the world-space fit.
 */
function project(
  points: Pt2[],
  box: { x: number; y: number; w: number; h: number },
  inset: number,
  rot: { c: number; s: number },
): Projector {
  const d = (q: Pt2): XY => [
    rot.c * q.x + rot.s * q.z,
    -rot.s * q.x + rot.c * q.z,
  ];
  const b = bounds(points.map(d));
  const spanX = Math.max(b.maxX - b.minX, 1e-6);
  const spanZ = Math.max(b.maxZ - b.minZ, 1e-6);
  const usableW = Math.max(box.w - 2 * inset, 1);
  const usableH = Math.max(box.h - 2 * inset, 1);
  const s = Math.min(usableW / spanX, usableH / spanZ);
  const ox = box.x + box.w / 2 - s * (b.minX + spanX / 2);
  const oy = box.y + box.h / 2 - s * (b.minZ + spanZ / 2);
  return {
    s,
    p: (q: Pt2) => {
      const [x, y] = d(q);
      return [ox + s * x, oy + s * y];
    },
    d,
  };
}

const add = (a: XY, b: XY, k = 1): XY => [a[0] + b[0] * k, a[1] + b[1] * k];

function lerp(a: XY, b: XY, t: number): XY {
  return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
}

function unit(a: XY, b: XY): XY {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const n = Math.hypot(dx, dy) || 1;
  return [dx / n, dy / n];
}

/* ------------------------------------------------------------------ *
 * The plan
 * ------------------------------------------------------------------ */

const INK = PALETTE.ink;

/**
 * Wall segments, openings and the light they let in, separated by paint
 * layer: light goes under the ink, jambs and glazing over it.
 */
function drawWalls(walls: WallPlan[], proj: Projector, contourPx: XY[]) {
  const glows: CardOp[] = [];
  const marks: CardOp[] = [];
  const solids: CardOp[] = [];
  for (const wall of walls) {
    const a = proj.p(wall.a);
    const b = proj.p(wall.b);
    // The wall's own outward normal. The plan is a uniform similarity
    // with no rotation, so a world unit vector is already a screen one.
    // The plan is a uniform similarity, so a world unit vector maps to a
    // screen unit vector under the same rotation. Jambs and glazing ride
    // this, so it has to be the ROTATED normal, not the world one.
    const out: XY = proj.d(wall.outward);

    const spans = [...wall.openings].sort((p, q) => p.t0 - q.t0);
    let cursor = 0;
    const solid: Array<[number, number]> = [];
    for (const op of spans) {
      const t0 = Math.max(0, Math.min(1, op.t0));
      const t1 = Math.max(0, Math.min(1, op.t1));
      if (t0 > cursor) solid.push([cursor, t0]);
      cursor = Math.max(cursor, t1);

      const p0 = lerp(a, b, t0);
      const p1 = lerp(a, b, t1);
      // Jambs: a short cross-stroke at each edge of the hole, the plan
      // convention that reads as "the wall stops here".
      for (const jamb of [p0, p1]) {
        marks.push({
          kind: "stroke",
          points: [add(jamb, out, -4.4), add(jamb, out, 4.4)],
          closed: false,
          stroke: alpha(INK, 0.85),
          width: 1.6,
        });
      }
      if (op.kind === "window") {
        // Glazing: the double line. A door or a bare opening gets jambs
        // and nothing across it, because nothing is across it.
        for (const off of [-2.6, 2.6]) {
          marks.push({
            kind: "stroke",
            points: [add(p0, out, off), add(p1, out, off)],
            closed: false,
            stroke: alpha(INK, 0.8),
            width: 1.3,
          });
        }
        const mid = lerp(p0, p1, 0.5);
        glows.push({
          kind: "glow",
          at: mid,
          radius: Math.max(0.85 * proj.s, 40),
          color: PALETTE.sun,
          clip: contourPx,
        });
      }
    }
    if (cursor < 1) solid.push([cursor, 1]);

    for (const [t0, t1] of solid) {
      if (t1 - t0 < 1e-6) continue;
      solids.push({
        kind: "stroke",
        points: [lerp(a, b, t0), lerp(a, b, t1)],
        closed: false,
        stroke: alpha(INK, 0.92),
        width: 2.2,
      });
    }
  }
  return { glows, solids, marks };
}

/** The dimension callout: extension lines, a dimension line, 45° ticks and
 * the length, exactly the architectural set the og-card drew by hand. */
function drawDimension(ops: CardOp[], wall: WallPlan, proj: Projector, text: string) {
  const a = proj.p(wall.a);
  const b = proj.p(wall.b);
  const out: XY = proj.d(wall.outward);
  const dir = unit(a, b);
  const hair = alpha(INK, 0.5);

  const GAP = 9;
  const EXT = 38;
  const DIM = 31;
  const LABEL = 48;

  for (const corner of [a, b]) {
    ops.push({
      kind: "stroke",
      points: [add(corner, out, GAP), add(corner, out, EXT)],
      closed: false,
      stroke: hair,
      width: 1,
    });
  }
  const da = add(a, out, DIM);
  const db = add(b, out, DIM);
  ops.push({
    kind: "stroke",
    points: [da, db],
    closed: false,
    stroke: hair,
    width: 1,
  });
  // 45° slash ticks, the convention the precedent used.
  const slash: XY = [
    (dir[0] + out[0]) / Math.SQRT2,
    (dir[1] + out[1]) / Math.SQRT2,
  ];
  for (const end of [da, db]) {
    ops.push({
      kind: "stroke",
      points: [add(end, slash, -4), add(end, slash, 4)],
      closed: false,
      stroke: alpha(INK, 0.85),
      width: 1.6,
    });
  }

  const anchor = add(lerp(a, b, 0.5), out, LABEL);
  // Never upside down: a half turn about the anchor keeps the text on the
  // same side of the wall and the right way up. Normalised to (-90, 90],
  // so a wall running right-to-left reads 0 rather than 360.
  const raw = (Math.atan2(dir[1], dir[0]) * 180) / Math.PI;
  let deg = ((raw % 360) + 540) % 360 - 180;
  if (deg > 90) deg -= 180;
  if (deg <= -90) deg += 180;
  ops.push({
    kind: "text",
    text,
    at: anchor,
    role: "mono",
    size: 20,
    weight: 500,
    italic: false,
    tracking: 0.04,
    fill: PALETTE.accent,
    align: "center",
    rotateDeg: deg,
    maxWidth: null,
  });
}

/* ------------------------------------------------------------------ *
 * The card
 * ------------------------------------------------------------------ */

export interface CardInput {
  measure: RoomMeasure;
  /** The room's DERIVED title (lib/voice.roomTitle). A room's own name is
   * private and does not travel — a name is user-authored, and
   * user-authored content on a shared artifact is a moderation surface
   * arriving through the side door (social-layer.md §9, decision 0207). */
  title: string;
  variant?: CardVariant;
}

/** The line that tells a stranger what they are looking at. */
export const CARD_SUBTITLE = "Every line here was measured, not drawn.";

/** The placeholder wordmark. One-file swap, like components/Wordmark.tsx —
 * see that file's note for everywhere else the name is rendered. */
const WORDMARK = "roomstudio";
const DOMAIN = "roomstudio.web.app";

export function layoutCard(input: CardInput): CardLayout {
  const { measure, title } = input;
  const variant: CardVariant = input.variant ?? "landscape";
  const frame: CardFrame = CARD_FRAMES[variant];
  const wide = variant === "landscape";
  const M = 64;

  const ops: CardOp[] = [
    { kind: "rect", at: [0, 0], w: frame.w, h: frame.h, fill: PALETTE.paper },
  ];

  // --- the plan ----------------------------------------------------
  const planBox = wide
    ? { x: 500, y: 48, w: frame.w - 500 - 40, h: frame.h - 96 }
    : { x: M, y: 300, w: frame.w - 2 * M, h: frame.h - 300 - 108 };
  // The inset is where the dimension callout lives: it is measured in
  // pixels, not meters, so it cannot be part of the world-space fit.
  const proj = project(measure.contour, planBox, 50, orientation(measure.datum));
  const contourPx = measure.contour.map(proj.p);

  ops.push({
    kind: "fill",
    points: contourPx,
    // The floor's measured colour, laid on as the plan's own tone — the
    // precedent's move, and the honest one: a measured colour shown as
    // colour rather than named as a word. An unobserved floor gets the
    // neutral ink wash and never an invented hue (0069).
    fill: measure.floorAlbedoHex
      ? alpha(measure.floorAlbedoHex, 0.09)
      : alpha(INK, 0.05),
  });

  const { glows, solids, marks } = drawWalls(measure.walls, proj, contourPx);
  // Light under the ink; the measured contour under the walls that stand
  // on it; jambs and glazing last.
  ops.push(...glows);
  ops.push({
    kind: "stroke",
    points: contourPx,
    closed: true,
    // Measured floor with no measured wall standing on it — the alcove
    // openings in the hero room are exactly this. Lighter, never absent.
    stroke: alpha(INK, 0.35),
    width: 1,
  });
  ops.push(...solids, ...marks);

  const datumText = measure.datum ? formatM(measure.datum.lengthM) : null;
  if (measure.datum && datumText) {
    drawDimension(ops, measure.datum, proj, datumText);
  }

  // --- the words ---------------------------------------------------
  const colW = wide ? 406 : frame.w - 2 * M;

  const markSize = 25;
  ops.push({ kind: "mark", at: [M, M], size: markSize });
  ops.push({
    kind: "text",
    text: WORDMARK.toUpperCase(),
    at: [M + markSize + 10, M + markSize * 0.72],
    role: "mono",
    size: 20,
    weight: 500,
    italic: false,
    tracking: 0.18,
    fill: alpha(INK, 0.7),
    align: "left",
    rotateDeg: 0,
    maxWidth: null,
  });

  const titleY = wide ? 206 : 150;
  ops.push({
    kind: "text",
    text: title,
    at: [M, titleY],
    role: "serif",
    size: wide ? 42 : 48,
    weight: 400,
    italic: false,
    tracking: -0.015,
    fill: INK,
    align: "left",
    rotateDeg: 0,
    maxWidth: colW,
  });
  ops.push({
    kind: "text",
    text: CARD_SUBTITLE,
    at: [M, titleY + (wide ? 48 : 52)],
    role: "serif",
    size: 22,
    weight: 400,
    italic: true,
    tracking: 0,
    fill: PALETTE.accent,
    align: "left",
    rotateDeg: 0,
    maxWidth: colW,
  });

  // The measurement plate: label over value, mono throughout, because a
  // dimension is machine data (0057).
  // Content at the top, the plate and the domain at the foot: the air in
  // between is the left column's answer to the drawing on the right.
  const plateY = wide ? 446 : titleY + 128;
  ops.push({
    kind: "stroke",
    points: [
      [M, plateY - 38],
      [M + colW, plateY - 38],
    ],
    closed: false,
    stroke: alpha(INK, 0.15),
    width: 1,
  });

  const ceilingText = measure.ceilingM !== null ? formatM(measure.ceilingM) : null;
  const floorText = formatM2(measure.floorAreaM2);
  // A zero count is a fact about the pipeline, not about the room, so it
  // is left off rather than printed as "0".
  const pieceText = measure.pieceCount > 0 ? String(measure.pieceCount) : null;

  const cells: Array<{ label: string; value: string; swatch?: string | null }> = [];
  if (ceilingText) cells.push({ label: "CEILING", value: ceilingText });
  cells.push({ label: "FLOOR", value: floorText, swatch: measure.floorAlbedoHex });
  if (pieceText) {
    cells.push({ label: measure.pieceCount === 1 ? "PIECE" : "PIECES", value: pieceText });
  }

  // A fixed column rather than a third of the width: with two cells, a
  // third-width step spreads the plate across the whole card and it stops
  // reading as one plate.
  const step = Math.min(colW / 3, 156);
  cells.forEach((cell, i) => {
    const x = M + i * step;
    const labelX = cell.swatch ? x + 16 : x;
    if (cell.swatch) {
      // The measured tone at full strength, as a bullet: the plan's wash
      // is 9% and the colour is otherwise unreadable.
      ops.push({ kind: "rect", at: [x, plateY - 9], w: 9, h: 9, fill: cell.swatch });
    }
    ops.push({
      kind: "text",
      text: cell.label,
      at: [labelX, plateY],
      role: "mono",
      size: 11,
      weight: 500,
      italic: false,
      tracking: 0.18,
      fill: alpha(INK, 0.45),
      align: "left",
      rotateDeg: 0,
      maxWidth: step - 20,
    });
    ops.push({
      kind: "text",
      text: cell.value,
      at: [x, plateY + 36],
      role: "mono",
      size: 26,
      weight: 400,
      italic: false,
      tracking: 0,
      fill: alpha(INK, 0.88),
      align: "left",
      rotateDeg: 0,
      maxWidth: step - 12,
    });
  });

  ops.push({
    kind: "text",
    text: DOMAIN,
    at: [M, frame.h - M],
    role: "mono",
    size: 18,
    weight: 400,
    italic: false,
    tracking: 0.08,
    fill: alpha(INK, 0.55),
    align: "left",
    rotateDeg: 0,
    maxWidth: colW,
  });

  return {
    width: frame.w,
    height: frame.h,
    ops,
    claims: {
      scalePxPerM: proj.s,
      title,
      ceilingText,
      floorText,
      pieceText,
      datum: measure.datum && datumText
        ? { wallId: measure.datum.wallId, lengthM: measure.datum.lengthM, text: datumText }
        : null,
      floorAlbedoHex: measure.floorAlbedoHex,
    },
  };
}
