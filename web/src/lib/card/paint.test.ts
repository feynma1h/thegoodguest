import { beforeAll, describe, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import path from "node:path";

import type { SceneAssets } from "@/lib/api/types";
import { layoutCard, type CardLayout } from "./layout";
import { measureRoom } from "./measure";
import { cardFileName, paintCard, resolveFonts, type PaintFonts } from "./paint";

/** A recording 2D context. jsdom ships no canvas, and the point here is
 * not pixels: it is that the painter draws what the display list says and
 * reaches for nothing else. */
function recorder() {
  const calls: Array<{ fn: string; args: unknown[] }> = [];
  const state: Record<string, unknown> = {};
  const record =
    (fn: string) =>
    (...args: unknown[]) => {
      calls.push({ fn, args });
      return undefined;
    };
  const ctx = {
    calls,
    state,
    fillRect: record("fillRect"),
    fillText: record("fillText"),
    beginPath: record("beginPath"),
    moveTo: record("moveTo"),
    lineTo: record("lineTo"),
    closePath: record("closePath"),
    fill: record("fill"),
    stroke: record("stroke"),
    clip: record("clip"),
    save: record("save"),
    restore: record("restore"),
    translate: record("translate"),
    scale: record("scale"),
    rotate: record("rotate"),
    measureText: (t: string) => ({ width: t.length * 7 }),
    createRadialGradient: () => ({ addColorStop: record("addColorStop") }),
  } as unknown as CanvasRenderingContext2D & {
    calls: typeof calls;
    state: typeof state;
  };
  // Style properties are plain assignments; capture the last value of each.
  for (const key of [
    "fillStyle",
    "strokeStyle",
    "lineWidth",
    "font",
    "textAlign",
    "textBaseline",
    "lineCap",
    "lineJoin",
    "letterSpacing",
  ]) {
    Object.defineProperty(ctx, key, {
      get: () => state[key],
      set: (v) => {
        state[key] = v;
        calls.push({ fn: `set:${key}`, args: [v] });
      },
      configurable: true,
    });
  }
  return ctx;
}

const FONTS: PaintFonts = { serif: "TestSerif", sans: "TestSans", mono: "TestMono" };

function heroLayout(): CardLayout {
  const doc = JSON.parse(
    readFileSync(path.resolve(__dirname, "../../../public/hero/room.json"), "utf8"),
  ) as SceneAssets;
  return layoutCard({
    measure: measureRoom(doc.shell, doc.manifest)!,
    title: "the August 8 room",
  });
}

beforeAll(() => {
  // The mark is drawn from the generated SVG path data via Path2D, which
  // jsdom has no implementation of.
  (globalThis as { Path2D?: unknown }).Path2D = class {
    constructor(readonly d?: string) {}
  };
});

describe("paintCard", () => {
  it("draws every op in the display list and reaches for nothing else", () => {
    const layout = heroLayout();
    const ctx = recorder();
    paintCard(ctx, layout, FONTS);

    const texts = layout.ops.filter((o) => o.kind === "text").length;
    const fills = layout.ops.filter((o) => o.kind === "fill").length;
    const strokes = layout.ops.filter((o) => o.kind === "stroke").length;
    const rects = layout.ops.filter((o) => o.kind === "rect").length;

    const drawn = (fn: string) => ctx.calls.filter((c) => c.fn === fn).length;
    expect(drawn("fillText")).toBe(texts);
    expect(drawn("stroke")).toBe(strokes);
    expect(drawn("fillRect")).toBeGreaterThanOrEqual(rects);
    expect(drawn("fill")).toBeGreaterThanOrEqual(fills);

    // No bitmap route exists on the painter at all: nothing it can call
    // would put a photograph, a splat render or any other image on a card.
    expect(ctx.calls.some((c) => /image|Image|Pattern/.test(c.fn))).toBe(false);
    expect("drawImage" in ctx).toBe(false);
  });

  it("sets every string in one of the three type roles", () => {
    const ctx = recorder();
    paintCard(ctx, heroLayout(), FONTS);
    const fonts = ctx.calls
      .filter((c) => c.fn === "set:font")
      .map((c) => String(c.args[0]));
    expect(fonts.length).toBeGreaterThan(0);
    for (const font of fonts) {
      expect(font).toMatch(/TestSerif|TestSans|TestMono/);
    }
  });

  it("leaves the context's letter spacing at zero after tracked text", () => {
    // A leaked letterSpacing would track everything drawn after it — and
    // the caller reuses one context for the whole card.
    const ctx = recorder();
    paintCard(ctx, heroLayout(), FONTS);
    const spacing = ctx.calls.filter((c) => c.fn === "set:letterSpacing");
    expect(spacing.length).toBeGreaterThan(0);
    expect(spacing[spacing.length - 1].args[0]).toBe("0px");
  });

  it("falls back to real families when the CSS variables are missing", () => {
    const fonts = resolveFonts({
      body: {},
      documentElement: {},
    } as unknown as Document);
    expect(fonts.serif).toMatch(/serif/);
    expect(fonts.sans).toMatch(/sans-serif/);
    expect(fonts.mono).toMatch(/monospace/);
  });

  it("reads next/font's hashed families off the document", () => {
    const style = {
      getPropertyValue: (name: string) =>
        ({
          "--font-source-serif": "__Source_Serif_4_abc123",
          "--font-instrument-sans": "__Instrument_Sans_abc123",
          "--font-plex-mono": "__IBM_Plex_Mono_abc123",
        })[name] ?? "",
    };
    vi.stubGlobal("getComputedStyle", () => style);
    const fonts = resolveFonts({ body: {} } as unknown as Document);
    expect(fonts.mono).toBe("__IBM_Plex_Mono_abc123");
    vi.unstubAllGlobals();
  });
});

describe("cardFileName", () => {
  it("derives the name from the title the card prints", () => {
    expect(cardFileName("the August 8 room")).toBe("the-august-8-room-card.png");
  });

  it("carries no identifier, whatever it is handed", () => {
    // The filename travels with the file, so it is on the same forbidden
    // list as the ink (social-layer.md §6.2).
    const name = cardFileName("the August 8 room");
    expect(name).not.toMatch(/[0-9a-f]{8}-[0-9a-f]{4}/i);
    expect(name).toMatch(/^[a-z0-9-]+\.png$/);
  });

  it("never produces a bare or path-bearing name", () => {
    for (const title of ["", "   ", "../../etc/passwd", "***"]) {
      const name = cardFileName(title);
      expect(name).toMatch(/^[a-z0-9-]+\.png$/);
      expect(name).not.toContain("/");
    }
  });
});
