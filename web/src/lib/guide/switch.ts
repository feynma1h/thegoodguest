/**
 * The room guide's switch and where its two outside pieces are served
 * (decision 0376).
 *
 * The room guide (packages/room-guide, behind api-public's /guide routes) is
 * shown on the room page only when this constant is true AND the scene's
 * assets carry a `scene_url` (a diorama scene.json). It is the 0340 pattern: a
 * named constant, not a build flag, so it is visible where it is read and one
 * edit takes the whole path out again. Off until the diorama pipeline is
 * merged and a cloud stage publishes scene.json, and the operator approves.
 *
 * The diorama viewer lives on the diorama branch (services/diorama/viewer/)
 * and the guide's player in packages/room-guide; neither is copied into this
 * app's source. scripts/guide-assets.mjs places both under public/ at dev and
 * build time (the viewer only once its folder exists), same-origin, because
 * the player is injected into the viewer's frame and shares its three.js.
 *
 * Read by: app/room/page.tsx (the switch), components/guide/GuideRoom.tsx.
 */

export const ROOM_GUIDE_ENABLED = false;

export function roomGuideEnabled(): boolean {
  return ROOM_GUIDE_ENABLED;
}

/** The diorama viewer's page. A file name rather than a folder index, so a
 * host that drops ".html" still resolves the viewer's relative imports. */
export const DIORAMA_VIEWER_PATH = "/diorama/viewer.html";

/** The guide's player (room-guide's web/player.js), injected into the viewer. */
export const GUIDE_PLAYER_PATH = "/guide/player.js";

/** The viewer's address for one scene. The opening reveal is skipped when the
 * room opens on a kept arrangement: the player places the pieces at once, and
 * the reveal would move them as it drops them in. */
export function viewerSrc(sceneUrl: string, arranged: boolean): string {
  const params = new URLSearchParams({ scene: sceneUrl });
  if (arranged) params.set("intro", "0");
  return `${DIORAMA_VIEWER_PATH}?${params.toString()}`;
}
