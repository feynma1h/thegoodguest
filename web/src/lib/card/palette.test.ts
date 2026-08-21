import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import path from "node:path";

import { alpha, PALETTE } from "./palette";

/** The card paints to a canvas, which cannot read a CSS custom property,
 * so the Good Guest tokens exist twice. This is the pin that makes the
 * second copy safe: if globals.css moves, this fails. */
describe("the card's palette is globals.css", () => {
  const css = readFileSync(
    path.resolve(__dirname, "../../app/globals.css"),
    "utf8",
  );

  const token = (name: string) => {
    const match = css.match(new RegExp(`--${name}:\\s*(#[0-9a-fA-F]{6})`));
    expect(match, `--${name} not found in globals.css`).toBeTruthy();
    return match![1].toLowerCase();
  };

  it("matches every token it copies", () => {
    expect(PALETTE.paper).toBe(token("paper"));
    expect(PALETTE.parchment).toBe(token("parchment"));
    expect(PALETTE.ink).toBe(token("ink"));
    expect(PALETTE.accent).toBe(token("accent"));
    expect(PALETTE.accentDeep).toBe(token("accent-deep"));
    expect(PALETTE.sun).toBe(token("sun"));
  });
});

describe("alpha", () => {
  it("expands a hex to rgba", () => {
    expect(alpha("#3a2d22", 0.5)).toBe("rgba(58, 45, 34, 0.5)");
  });

  it("tolerates a hex with no hash", () => {
    expect(alpha("715b47", 0.09)).toBe("rgba(113, 91, 71, 0.09)");
  });
});
