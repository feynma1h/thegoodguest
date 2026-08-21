/**
 * The card's one renderer: walks a CardLayout onto a 2D canvas context.
 *
 * It makes no decisions. Every coordinate, string and colour arrives
 * decided from `layout.ts`; this file knows about fonts, gradients and
 * Path2D and nothing else. Keeping it dumb is what lets the layout be
 * pinned without a browser, and what guarantees the preview a person looks
 * at is byte-identical to the file they download — the preview IS this
 * canvas, and the download is `toBlob` of the same one.
 *
 * WHY CANVAS AND NOT SVG. An SVG rasterized through an <img> renders in an
 * isolated context with no access to the document's fonts, so a card drawn
 * that way silently falls back to system faces unless every face is
 * inlined as a base64 data URI. Canvas text uses the document's own loaded
 * fonts. The cost is that the family names have to be resolved at runtime
 * (next/font mints hashed families), which `resolveFonts` does.
 */

import {
  FACES,
  MARK_FLOOR,
  MARK_INK,
  MARK_WALL,
  PLATE_FRAMED,
} from "@/components/markGeometry";
import { alpha } from "./palette";
import type { CardLayout, CardOp, TextOp, XY } from "./layout";

export interface PaintFonts {
  serif: string;
  sans: string;
  mono: string;
}

/** Last-resort stacks, used only if the CSS variables are missing (a bare
 * canvas in a test page, say). The real families come from next/font. */
const FALLBACK: PaintFonts = {
  serif: "Source Serif 4, Georgia, serif",
  sans: "Instrument Sans, system-ui, sans-serif",
  mono: "IBM Plex Mono, ui-monospace, monospace",
};

/**
 * The real family names, read off the live document. next/font generates a
 * hashed family per face and exposes it through the CSS variables set in
 * app/layout.tsx, so this is the only correct source.
 */
export function resolveFonts(doc: Document): PaintFonts {
  const el = doc.body ?? doc.documentElement;
  if (!el || typeof getComputedStyle !== "function") return FALLBACK;
  const style = getComputedStyle(el);
  const pick = (name: string, fallback: string) => {
    const value = style.getPropertyValue(name).trim();
    return value.length > 0 ? value : fallback;
  };
  return {
    serif: pick("--font-source-serif", FALLBACK.serif),
    sans: pick("--font-instrument-sans", FALLBACK.sans),
    mono: pick("--font-plex-mono", FALLBACK.mono),
  };
}

function fontString(op: TextOp, fonts: PaintFonts): string {
  const family = fonts[op.role];
  return `${op.italic ? "italic " : ""}${op.weight} ${op.size}px ${family}`;
}

/**
 * Wait until every face the card actually uses has loaded. next/font
 * lazy-loads by face, so a weight the page has not used yet is not in
 * memory — and canvas text does not trigger a load, it just falls back
 * silently. Derived from the layout so a new face cannot be forgotten.
 */
export async function ensureCardFonts(
  doc: Document,
  layout: CardLayout,
  fonts: PaintFonts,
): Promise<void> {
  const faces = doc.fonts;
  if (!faces) return;
  const wanted = new Set<string>();
  for (const op of layout.ops) {
    if (op.kind === "text") wanted.add(fontString(op, fonts));
  }
  await Promise.all(
    [...wanted].map((f) => faces.load(f).catch(() => undefined)),
  );
  await faces.ready.catch(() => undefined);
}

function tracePolygon(ctx: CanvasRenderingContext2D, points: XY[], closed: boolean) {
  ctx.beginPath();
  points.forEach(([x, y], i) => (i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y)));
  if (closed) ctx.closePath();
}

/** Whether this context honours `letterSpacing` (Safari < 17.4 does not). */
function supportsLetterSpacing(ctx: CanvasRenderingContext2D): boolean {
  return "letterSpacing" in ctx;
}

/** Tracked text, drawn a glyph at a time. Only reached on a context with
 * no `letterSpacing`; without it the tracked mono eyebrow would set solid
 * and read as a different mark. */
function drawTracked(ctx: CanvasRenderingContext2D, op: TextOp) {
  const extra = op.tracking * op.size;
  const chars = [...op.text];
  const widths = chars.map((c) => ctx.measureText(c).width);
  const total =
    widths.reduce((a, b) => a + b, 0) + extra * Math.max(chars.length - 1, 0);
  let x = op.align === "center" ? -total / 2 : op.align === "right" ? -total : 0;
  const prev = ctx.textAlign;
  ctx.textAlign = "left";
  chars.forEach((c, i) => {
    ctx.fillText(c, x, 0);
    x += widths[i] + extra;
  });
  ctx.textAlign = prev;
}

function drawText(ctx: CanvasRenderingContext2D, op: TextOp, fonts: PaintFonts) {
  ctx.save();
  ctx.translate(op.at[0], op.at[1]);
  if (op.rotateDeg !== 0) ctx.rotate((op.rotateDeg * Math.PI) / 180);
  ctx.font = fontString(op, fonts);
  ctx.fillStyle = op.fill;
  ctx.textAlign = op.align;
  ctx.textBaseline = "alphabetic";
  if (op.tracking !== 0 && !supportsLetterSpacing(ctx)) {
    drawTracked(ctx, op);
  } else {
    if (op.tracking !== 0) ctx.letterSpacing = `${op.tracking}em`;
    if (op.maxWidth !== null) ctx.fillText(op.text, 0, 0, op.maxWidth);
    else ctx.fillText(op.text, 0, 0);
    if (op.tracking !== 0) ctx.letterSpacing = "0px";
  }
  ctx.restore();
}

/** The mark, from the generated geometry in its 1024 viewBox. The framed
 * plate: the card is a light field, and the rim band is what separates the
 * mark from it (0176/0193). */
function drawMark(ctx: CanvasRenderingContext2D, at: XY, size: number) {
  ctx.save();
  ctx.translate(at[0], at[1]);
  ctx.scale(size / 1024, size / 1024);
  ctx.fillStyle = MARK_INK;
  ctx.fill(new Path2D(PLATE_FRAMED));
  ctx.fillStyle = MARK_WALL;
  ctx.fill(new Path2D(FACES[0]));
  ctx.fill(new Path2D(FACES[1]));
  ctx.fillStyle = MARK_FLOOR;
  ctx.fill(new Path2D(FACES[2]));
  ctx.restore();
}

/** Daylight through a window: the precedent's three stops, clipped to the
 * room so light never spills outside the measured floor. */
function drawGlow(
  ctx: CanvasRenderingContext2D,
  at: XY,
  radius: number,
  color: string,
  clip: XY[],
) {
  ctx.save();
  tracePolygon(ctx, clip, true);
  ctx.clip();
  const g = ctx.createRadialGradient(at[0], at[1], 0, at[0], at[1], radius);
  g.addColorStop(0, alpha(color, 0.28));
  g.addColorStop(0.55, alpha(color, 0.11));
  g.addColorStop(1, alpha(color, 0));
  ctx.fillStyle = g;
  ctx.fillRect(at[0] - radius, at[1] - radius, radius * 2, radius * 2);
  ctx.restore();
}

/**
 * Paint the whole card in LAYOUT coordinates. The caller owns the device
 * pixel ratio: set a scale transform first and size the canvas to match.
 */
export function paintCard(
  ctx: CanvasRenderingContext2D,
  layout: CardLayout,
  fonts: PaintFonts,
): void {
  ctx.lineCap = "butt";
  ctx.lineJoin = "miter";
  for (const op of layout.ops as CardOp[]) {
    switch (op.kind) {
      case "rect":
        ctx.fillStyle = op.fill;
        ctx.fillRect(op.at[0], op.at[1], op.w, op.h);
        break;
      case "fill":
        tracePolygon(ctx, op.points, true);
        ctx.fillStyle = op.fill;
        ctx.fill();
        break;
      case "stroke":
        tracePolygon(ctx, op.points, op.closed);
        ctx.strokeStyle = op.stroke;
        ctx.lineWidth = op.width;
        ctx.stroke();
        break;
      case "glow":
        drawGlow(ctx, op.at, op.radius, op.color, op.clip);
        break;
      case "mark":
        drawMark(ctx, op.at, op.size);
        break;
      case "text":
        drawText(ctx, op, fonts);
        break;
    }
  }
}

/**
 * The download's filename. Derived from the same title the card prints,
 * so it carries no scene id, no bundle id and nothing that resolves back
 * to an account — the filename travels with the file.
 */
export function cardFileName(title: string): string {
  const slug = title
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return `${slug.length > 0 ? slug : "room"}-card.png`;
}
