/**
 * Pins for lib/clipSign — the one place the viewer's yaw-sign convention
 * lives (decisions 0135/0112).
 *
 * The semantic pin applies three.js's R_y to a local axis and asserts which
 * WORLD direction it lands in, against the server's own convention
 * (room_geometry.OrientedBox.local_axes_xz: local +x maps to world
 * (cos θ, sin θ) in XZ). That pins the meaning, not the negation — a future
 * "simplification" that hands three.js the raw yaw fails loudly.
 */

import { describe, expect, it } from "vitest";

import { viewerYawRad } from "./clipSign";

/** three.js R_y(phi) applied to (x, y, z) — same matrix
 * setFromAxisAngle([0,1,0], phi) produces. */
function rotY(phi: number, [x, y, z]: [number, number, number]): [number, number, number] {
  const c = Math.cos(phi);
  const s = Math.sin(phi);
  return [x * c + z * s, y, -x * s + z * c];
}

describe("viewerYawRad", () => {
  it("local +x lands at world (cos θ, sin θ) — the server convention", () => {
    // The spike bed's real yaw (θ = −0.8109, decision 0135). The box's
    // local +x must land where room_geometry.local_axes_xz puts it:
    // (cos θ, 0, sin θ).
    const theta = -0.8109;
    const [x, , z] = rotY(viewerYawRad(theta), [1, 0, 0]);
    expect(x).toBeCloseTo(Math.cos(theta), 12);
    expect(z).toBeCloseTo(Math.sin(theta), 12);
  });

  it("is NOT the raw yaw — the retired shipped sign sat 2θ off the measurement", () => {
    // The pre-0112 renderer handed three.js the raw yaw, leaving the box
    // 2θ from the measured one (the misrotation both 0135 instruments read
    // as 19–27° wall skew, and the 0112 walk saw as amputated table legs).
    // Pin that the applied sign differs from raw by exactly that 2θ, so a
    // regression to the shipped sign is loud.
    const theta = 0.5633; // rp7 storage/bed
    const applied = rotY(viewerYawRad(theta), [1, 0, 0]);
    const raw = rotY(theta, [1, 0, 0]);
    const dot = applied[0] * raw[0] + applied[1] * raw[1] + applied[2] * raw[2];
    expect(Math.acos(dot)).toBeCloseTo(2 * theta, 10);
  });

  it("zero yaw is a fixed point — axis-aligned boxes cannot move", () => {
    // === not toBe: negating 0 yields -0, which Object.is distinguishes
    // but rotation does not.
    expect(viewerYawRad(0) === 0).toBe(true);
  });
});
