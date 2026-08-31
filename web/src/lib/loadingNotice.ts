/**
 * When the viewer may say "Assembling the room…" — as a table, not as a
 * boolean the renderer happens to be holding.
 *
 * The notice is honest on the room page, where a scene is tens to hundreds
 * of megabytes and the wait is measured in seconds. It was dishonest on
 * the landing hero, whose fixture carries ZERO splats (decision 0122): the
 * only thing left to wait for there is WebGL context creation and a
 * handful of quads, so the label announced a byte wait that structurally
 * cannot happen and then vanished — a flash whose length was whatever the
 * GPU took that morning. Measured live 2026-08-31: gone before 706 ms on
 * one load, and on two warm loads gone so fast an 8 ms DOM poll never
 * caught it at all.
 *
 * A notice whose visibility is a race reads worse than one that is always
 * there or never there. So the rule is: STATE A WAIT ONLY ONCE THERE IS
 * ONE. Two constants say it —
 *
 *   - it does not appear until the load has run past `NOTICE_DELAY_MS`, so
 *     a load that finishes first is never narrated;
 *   - having appeared, it stays for `NOTICE_MIN_VISIBLE_MS`, so a load
 *     that finishes just past the threshold cannot replace a long flash
 *     with a shorter one. Delay alone narrows the race; it does not close
 *     it.
 *
 * The window is a pure function of two instants for the same reason
 * lib/reveal's score is (decision 0097): timing cannot be judged in a
 * throttled automation browser, so it is verified as a table instead.
 *
 * The hook lives here rather than in SplatViewer for the same reason: a
 * browser cannot be made to load slowly on demand, so "does it still
 * appear on a real wait?" is unanswerable there — measured 2026-08-31,
 * where a 13 MB room read from disk cache finished well inside the delay
 * and Spark's worker fetches are invisible to main-thread resource
 * timing. Under fake timers it is exact.
 */

import { useEffect, useRef, useState } from "react";

/** How long a load must run before it is worth narrating. */
export const NOTICE_DELAY_MS = 400;
/** Once up, the shortest the notice may stay. */
export const NOTICE_MIN_VISIBLE_MS = 300;

export interface NoticeWindow {
  /** When the notice goes up. */
  appearsAtMs: number;
  /** When it comes down. `Infinity` while the load is still running. */
  hidesAtMs: number;
}

/**
 * The window the notice occupies for a load that began at `loadStartedMs`
 * and ended at `loadEndedMs` (null while it is still running), or null
 * when the load finished early enough that the notice never appears at
 * all — the landing hero's whole case.
 *
 * Both instants are on one monotonic clock (`performance.now()`); the
 * function neither reads a clock nor cares which one, which is what makes
 * it a table.
 */
export function noticeWindow({
  loadStartedMs,
  loadEndedMs,
}: {
  loadStartedMs: number;
  loadEndedMs: number | null;
}): NoticeWindow | null {
  const appearsAtMs = loadStartedMs + NOTICE_DELAY_MS;
  // Finished before it would have gone up: nothing was ever said.
  if (loadEndedMs !== null && loadEndedMs <= appearsAtMs) return null;
  return {
    appearsAtMs,
    hidesAtMs:
      loadEndedMs === null
        ? Number.POSITIVE_INFINITY
        : Math.max(loadEndedMs, appearsAtMs + NOTICE_MIN_VISIBLE_MS),
  };
}

/**
 * Whether the notice is on screen, applying `noticeWindow` with two
 * timers — one to raise it, one to lower it. This supplies the clock and
 * nothing else; the decision is the pure function above.
 */
export function useLoadingNotice(loading: boolean): boolean {
  const [visible, setVisible] = useState(false);
  const startedAtRef = useRef<number | null>(null);

  useEffect(() => {
    if (loading) {
      startedAtRef.current = performance.now();
      const timer = window.setTimeout(() => setVisible(true), NOTICE_DELAY_MS);
      return () => window.clearTimeout(timer);
    }
    const loadStartedMs = startedAtRef.current;
    startedAtRef.current = null;
    if (loadStartedMs === null) return;
    const now = performance.now();
    const span = noticeWindow({ loadStartedMs, loadEndedMs: now });
    // Null means it never went up: the load beat the delay, and the
    // pending raise-timer was already cleared by this effect's teardown.
    if (span === null) {
      setVisible(false);
      return;
    }
    const timer = window.setTimeout(
      () => setVisible(false),
      Math.max(0, span.hidesAtMs - now),
    );
    return () => window.clearTimeout(timer);
  }, [loading]);

  return visible;
}
