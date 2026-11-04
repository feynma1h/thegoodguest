/**
 * The room's optional finish and furniture twins, read from the scene's
 * assets response.
 *
 * api-public signs links to two optional siblings of shell.json in the scene's
 * folder — `finish_url` (lib/shellFinish) and `furniture_url` (lib/furniture),
 * each null when the file is not there (decision 0313). Nothing here runs unless
 * the finish flag is on (NEXT_PUBLIC_SHELL_FINISH=1): without it no request is
 * made and the room is exactly what it was. With it, each file is fetched and
 * validated against the shell it would dress, and anything that fails — a
 * network error, bad JSON, a finish for a different wall count — comes back
 * null, so the room draws as before.
 */

import type { SceneAssets } from "@/lib/api/types";
import { parseFurniture, type FurnitureBundle } from "@/lib/furniture";
import { parseFinish, shellFinishEnabled, type ShellFinish } from "@/lib/shellFinish";

export interface ShellExtras {
  finish: ShellFinish | null;
  furniture: FurnitureBundle | null;
}

export const NO_EXTRAS: ShellExtras = { finish: null, furniture: null };

/** Validate parsed documents against a shell with `wallCount` walls. Never throws.
 * Twins stand in a finished room: without a finish that fits, draw neither. */
export function shellExtras(wallCount: number, finishDoc: unknown, furnitureDoc: unknown): ShellExtras {
  try {
    const finish = finishDoc == null ? null : parseFinish(finishDoc, wallCount);
    if (!finish) return NO_EXTRAS;
    const furniture = furnitureDoc == null ? null : parseFurniture(furnitureDoc);
    return { finish, furniture };
  } catch {
    return NO_EXTRAS;
  }
}

async function fetchJson(url: string): Promise<unknown> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json();
}

/** Fetch and validate the extras an assets response links to, for the shell
 * the viewer will draw (`wallCount` = its wall planes). Resolves, never rejects. */
export async function loadShellExtras(
  assets: Pick<SceneAssets, "finish_url" | "furniture_url">,
  wallCount: number,
  get: (url: string) => Promise<unknown> = fetchJson,
  enabled: boolean = shellFinishEnabled(),
): Promise<ShellExtras> {
  if (!enabled || !assets.finish_url) return NO_EXTRAS;
  const orNull = (url: string | null | undefined) =>
    url ? get(url).catch(() => null) : Promise.resolve(null);
  const [finishDoc, furnitureDoc] = await Promise.all([orNull(assets.finish_url), orNull(assets.furniture_url)]);
  return shellExtras(wallCount, finishDoc, furnitureDoc);
}
