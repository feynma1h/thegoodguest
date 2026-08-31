/**
 * The landing hero's room — what it is, and what it deliberately isn't.
 *
 * THE HERO IS THE REVEAL, NOT A ROOM (decision 0122). The landing page
 * plays the first two movements of the reveal choreography (lib/reveal,
 * decision 0097) — the measured boundary drawing itself, then the
 * surfaces materializing in place — against a REAL captured room's
 * GEOMETRY. No object splats. The copy beside it waits for none of it:
 * the page's words and the room's first frame arrive together.
 *
 * The fixture is one static file: public/hero/room.json, a `SceneAssets`
 * document carrying a real shell.json v3 verbatim with an EMPTY objects
 * list. It goes through the production `assembleScene` unchanged — the
 * hero consumes the same contract the product does, so a change to the
 * shell contract breaks here loudly rather than drifting.
 *
 * Why geometry only, so nobody "improves" this by adding the room's
 * furniture back:
 *   - A stranger's lived-in bedroom is anti-premium at hero scale. The
 *     thesis is the best version of YOUR home; a demo room is necessarily
 *     someone else's clutter.
 *   - Placement today is roughly half the pieces on the best room, with
 *     known artifacts. Half a room is worse than no room — it is an
 *     anti-demo.
 *   - Bytes. This fixture is ~3.5 KB. The cheapest legible piece of
 *     furniture from the same scene is ~18 MB, and the room's full splat
 *     set is ~460 MB.
 *   - Without splats there are no possessions on a public origin — just a
 *     floor polygon, wall heights and measured colours.
 *
 * VARIANT B exists only as a taste probe (?hero=b): exactly one piece
 * settling in at the end, named, as the score already does. Its splat is
 * deliberately NOT part of the shipped fixture — a real object splat is a
 * possession, and public/dev-fixtures shipping real-room artifacts to a
 * public origin is a mistake this project has already made once. Stage
 * public/hero/piece.json (gitignored) to look at it; absent, ?hero=b
 * degrades to the shipped variant and the hero still plays.
 */

import { assembleScene } from "@/lib/api/types";
import type { AssembledScene, FusedObject, SceneAssets } from "@/lib/api/types";

/** The shipped fixture: geometry + parametric materials, zero objects. */
export const HERO_ROOM_URL = "/hero/room.json";
/** The variant-B probe's piece. Gitignored; absent in the shipped build. */
export const HERO_PIECE_URL = "/hero/piece.json";

export type HeroVariant = "a" | "b";

/**
 * Which variant a URL asks for. `?hero=b` opts into the one-piece probe;
 * anything else — including no query at all — is the shipped hero.
 */
export function heroVariant(search: string): HeroVariant {
  const raw = new URLSearchParams(search).get("hero");
  return raw?.toLowerCase() === "b" ? "b" : "a";
}

/** The variant-B sidecar: one placed object plus its splat URL. */
export interface HeroPiece {
  objects: FusedObject[];
  asset_urls: Record<string, string>;
}

/** Merge the probe's piece into the fixture. Pure — the fetch lives in
 * the caller so this stays testable without a network. */
export function withPiece(assets: SceneAssets, piece: HeroPiece): SceneAssets {
  return {
    ...assets,
    manifest: { ...assets.manifest, objects: piece.objects },
    asset_urls: { ...assets.asset_urls, ...piece.asset_urls },
  };
}

/**
 * The hero's scene, or null when the fixture cannot be read — in which
 * case the landing page simply has no room and the copy lands at once.
 * Variant B silently falls back to the shipped fixture when its sidecar
 * is absent: a missing probe must never cost a visitor the hero.
 */
export async function loadHeroScene(
  variant: HeroVariant = "a",
  fetchImpl: typeof fetch = fetch,
): Promise<AssembledScene | null> {
  let assets: SceneAssets;
  try {
    const resp = await fetchImpl(HERO_ROOM_URL);
    if (!resp.ok) return null;
    assets = (await resp.json()) as SceneAssets;
  } catch {
    return null;
  }

  if (variant === "b") {
    try {
      const resp = await fetchImpl(HERO_PIECE_URL);
      if (resp.ok) {
        assets = withPiece(assets, (await resp.json()) as HeroPiece);
      }
    } catch {
      // No piece staged — the shipped hero, which is the point of the A/B.
    }
  }

  const scene = assembleScene(assets);
  if (!scene.shell?.length && scene.splats.length === 0) return null;
  return scene;
}
