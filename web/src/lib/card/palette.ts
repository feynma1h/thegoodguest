/**
 * The card's ink, as concrete values.
 *
 * The card paints to a canvas, and a canvas cannot read a CSS custom
 * property — so the Good Guest tokens, which live in `app/globals.css` as
 * `--paper`/`--ink`/`--accent`/`--sun`, have to exist here as literals.
 * `palette.test.ts` parses globals.css and fails if the two ever diverge,
 * which is the only thing that makes a second copy safe.
 *
 * Type roles are decision 0057's: serif is display, sans is UI, mono is
 * eyebrow labels and machine data. A dimension is machine data.
 */

/** The Good Guest tokens. Mirrors `:root` in app/globals.css. */
export const PALETTE = {
  paper: "#f9f2ec",
  parchment: "#ebe5df",
  ink: "#282723",
  accent: "#c04d3e",
  accentDeep: "#a54235",
  sun: "#c9a25e",
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
