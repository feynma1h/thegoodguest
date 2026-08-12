/**
 * clipSign — the yaw sign the viewer uses when it builds yaw-oriented
 * boxes (the 0104 `splat_clip` volume and the 0131 measured outline) from
 * the server's `yaw_rad`.
 *
 * THE CONVENTION (decision 0135, measured on all four walk rooms; made the
 * default by the operator's A/B walk, decision 0112, 2026-08-12):
 *
 *   `yaw_rad` rotates (x, z) as an ordinary 2D plane:
 *   x = u·cosθ − v·sinθ, z = u·sinθ + v·cosθ. This is what perception's
 *   own removed_fraction accounting uses, what the stage-2 solver uses
 *   (room_geometry.OrientedBox.local_axes_xz), and the sign under which
 *   RoomPlan boxes come out wall-aligned (14/15 at exactly 0.0°).
 *
 * three.js's `setFromAxisAngle([0,1,0], θ)` is the OPPOSITE rotation
 * (x = u·cosθ + v·sinθ, z = −u·sinθ + v·cosθ), so the yaw handed to
 * three.js must be negated — that negation is this module's whole job,
 * kept as a pure function so the convention is testable and has exactly
 * one home. The un-negated sign ("shipped", what every room rendered from
 * 0104 until the 0112 walk) left the box 2θ from the one the server
 * measured — amputating table legs at 35% and rendering a wardrobe as a
 * diagonal sliver; the walk retired it and the `?clipsign` toggle with it.
 *
 * Read by: SplatViewer (both yaw consumers — clip volumes and outlines).
 */

/** The yaw to hand three.js (`setFromAxisAngle([0,1,0], ·)`, or the
 * equivalent inline cos/sin map) so the built box lands where the server
 * measured it. */
export function viewerYawRad(yawRad: number): number {
  return -yawRad;
}
