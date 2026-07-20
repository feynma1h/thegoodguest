/**
 * The hold rule's memory (design §4): the reveal plays once per room per
 * browser; after that, the room opens directly. localStorage-backed —
 * per-device by design until accounts carry preferences. Safe under SSG
 * (no window at prerender) and under blocked storage (private mode):
 * failures read as "not seen", which just means the reveal plays again.
 */

const KEY_PREFIX = "roomstudio:reveal-seen:";

export function hasSeenReveal(sceneId: string): boolean {
  if (typeof window === "undefined") return false;
  try {
    return window.localStorage.getItem(KEY_PREFIX + sceneId) === "1";
  } catch {
    return false;
  }
}

export function markRevealSeen(sceneId: string): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(KEY_PREFIX + sceneId, "1");
  } catch {
    // Storage unavailable — the reveal will simply play again next time.
  }
}
