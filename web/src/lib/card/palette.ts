/**
 * The card's ink, as concrete values.
 *
 * The card paints to a canvas, and a canvas cannot read a CSS custom
 * property — so the Good Guest tokens, which live in `app/globals.css` as
 * `--paper`/`--ink`/`--accent`/`--sun`, have to exist here as literals.
 * `palette.test.ts` parses globals.css and fails if the two ever diverge,
 * which is the only thing that makes a second copy safe.
 *
 * Type roles are decision 0361's: serif is display, sans is UI, mono is
 * measurements. A dimension is a measurement.
 */

/** The Good Guest tokens. Mirrors `:root` in app/globals.css. */
export const PALETTE = {
  paper: "#f5f6f8",
  parchment: "#e4e9ed",
  ink: "#121a23",
  accent: "#c04d3e",
  accentDeep: "#a54235",
  sun: "#f0b26a",
} as const;

/** `rgba()` for one of the palette's hexes at a given alpha. */
export function alpha(hex: string, a: number): string {
  const text = hex.replace("#", "");
  const r = parseInt(text.slice(0, 2), 16);
  const g = parseInt(text.slice(2, 4), 16);
  const b = parseInt(text.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${a})`;
}

/**
 * The three type roles. The painter resolves these to the real family
 * names at paint time — next/font mints hashed families, so the only
 * correct source is the computed value of the CSS variable on the live
 * document (see paint.ts's `resolveFonts`).
 */
export type CardFontRole = "serif" | "sans" | "mono";
