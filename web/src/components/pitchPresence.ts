"use client";

/**
 * Whether the landing's pitch is on screen. "/" shows the pitch to a first
 * visitor and a greeting to a returning one, and the nav's section links
 * (How it works, The guest, Privacy) point into the pitch — so they show
 * only while it is there. The static page renders the pitch, so the server
 * answer is "showing".
 */

import { useEffect, useSyncExternalStore } from "react";

let mounted = 0;
const listeners = new Set<() => void>();

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Called by the pitch: it is on screen for as long as it is mounted. */
export function usePitchPresence() {
  useEffect(() => {
    mounted += 1;
    listeners.forEach((l) => l());
    return () => {
      mounted -= 1;
      listeners.forEach((l) => l());
    };
  }, []);
}

/** Read by the nav. */
export function usePitchShowing(): boolean {
  return useSyncExternalStore(
    subscribe,
    () => mounted > 0,
    () => true,
  );
}
