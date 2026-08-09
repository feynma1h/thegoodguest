/**
 * clipSign — which yaw sign the viewer uses when it builds yaw-oriented
 * boxes (the 0104 `splat_clip` volume and the 0131 measured outline) from
 * the server's `yaw_rad`.
 *
 * THE TWO CONVENTIONS (decision 0135, measured on all four walk rooms):
 *
 *   server / "measured"  — `yaw_rad` rotates (x, z) as an ordinary 2D
 *                          plane:  x = u·cosθ − v·sinθ, z = u·sinθ + v·cosθ.
 *                          This is what perception's own removed_fraction
 *                          accounting uses, what the stage-2 solver uses
 *                          (room_geometry.OrientedBox.local_axes_xz), and
 *                          the sign under which RoomPlan boxes come out
 *                          wall-aligned (14/15 at exactly 0.0°).
 *
 *   "shipped"            — what the renderer has applied since 0104:
 *                          three.js setFromAxisAngle([0,1,0], θ), which is
 *                          x = u·cosθ + v·sinθ, z = −u·sinθ + v·cosθ — the
 *                          OPPOSITE rotation, leaving the box 2θ from the
 *                          one the server measured.
 *
 * three.js's R_y(−θ) equals the measured convention, so this module's whole
 * job is one conditional negation — kept as a pure function so the choice
 * is testable and has exactly one home.
 *
 * `?clipsign=measured` on the dev viewer is the A/B the 0135 walk judges
 * (decision 0112). The default stays "shipped" everywhere until the
 * operator rules; nothing on a product route reads the toggle.
 *
 * Read by: SplatViewer (both yaw consumers), app/viewer (URL param).
 */

export type ClipSign = "shipped" | "measured";

/** Parse the dev-viewer URL param. Anything but the literal "measured" —
 * absent, empty, misspelled — is the shipped default, so the toggle can
 * never change a render by accident. */
export function parseClipSign(raw: string | null): ClipSign {
  return raw === "measured" ? "measured" : "shipped";
}

/** The yaw to hand three.js (`setFromAxisAngle([0,1,0], ·)`, or the
 * equivalent inline cos/sin map) so the built box is oriented per `sign`. */
export function viewerYawRad(yawRad: number, sign: ClipSign): number {
  return sign === "measured" ? -yawRad : yawRad;
}
