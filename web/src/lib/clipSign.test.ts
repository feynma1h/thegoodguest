/**
 * Pins for lib/clipSign — the one place the viewer's yaw-sign choice lives
 * (decisions 0135/0112).
 *
 * The semantic pins apply three.js's R_y to a local axis and assert which
 * WORLD direction it lands in under each sign, against the server's own
 * convention (room_geometry.OrientedBox.local_axes_xz: local +x maps to
 * world (cos θ, sin θ) in XZ). That pins the meaning, not the negation —
 * a future "simplification" that flips either convention fails loudly.
 */

import { describe, expect, it } from "vitest";

import { parseClipSign, viewerYawRad } from "./clipSign";

/** three.js R_y(phi) applied to (x, y, z) — same matrix
 * setFromAxisAngle([0,1,0], phi) produces. */
function rotY(phi: number, [x, y, z]: [number, number, number]): [number, number, number] {
  const c = Math.cos(phi);
  const s = Math.sin(phi);
  return [x * c + z * s, y, -x * s + z * c];
}

describe("parseClipSign", () => {
  it("is shipped unless the param is exactly 'measured'", () => {
    expect(parseClipSign(null)).toBe("shipped");
    expect(parseClipSign("")).toBe("shipped");
    expect(parseClipSign("shipped")).toBe("shipped");
    expect(parseClipSign("Measured")).toBe("shipped");
    expect(parseClipSign("1")).toBe("shipped");
    expect(parseClipSign("measured")).toBe("measured");
  });
});

describe("viewerYawRad", () => {
  it("leaves the shipped sign untouched — the default render cannot drift", () => {
    expect(viewerYawRad(0.7599, "shipped")).toBe(0.7599);
    expect(viewerYawRad(-0.8109, "shipped")).toBe(-0.8109);
  });

  it("measured: local +x lands at world (cos θ, sin θ) — the server convention", () => {
    // The spike bed's real yaw (θ = −0.8109, decision 0135). Under the
    // measured convention the box's local +x must land where
    // room_geometry.local_axes_xz puts it: (cos θ, 0, sin θ).
    const theta = -0.8109;
    const [x, , z] = rotY(viewerYawRad(theta, "measured"), [1, 0, 0]);
    expect(x).toBeCloseTo(Math.cos(theta), 12);
    expect(z).toBeCloseTo(Math.sin(theta), 12);
  });

  it("shipped: local +x lands at world (cos θ, −sin θ) — 2θ from the measurement", () => {
    const theta = -0.8109;
    const [x, , z] = rotY(viewerYawRad(theta, "shipped"), [1, 0, 0]);
    expect(x).toBeCloseTo(Math.cos(theta), 12);
    expect(z).toBeCloseTo(-Math.sin(theta), 12);
  });

  it("the two signs differ by the 2θ the instruments measured", () => {
    // Angle between the two boxes' local +x axes = 2θ (mod symmetry) —
    // the misrotation both 0135 instruments read as 19–27° wall skew.
    const theta = 0.5633; // rp7 storage/bed
    const a = rotY(viewerYawRad(theta, "shipped"), [1, 0, 0]);
    const b = rotY(viewerYawRad(theta, "measured"), [1, 0, 0]);
    const dot = a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
    expect(Math.acos(dot)).toBeCloseTo(2 * theta, 10);
  });
});
