/**
 * The notice's window, as a table. The instants are relative to an
 * arbitrary origin (1000) to prove nothing depends on a zero base.
 */

import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  NOTICE_DELAY_MS,
  NOTICE_MIN_VISIBLE_MS,
  noticeWindow,
  useLoadingNotice,
} from "@/lib/loadingNotice";

const T0 = 1000;
const APPEARS = T0 + NOTICE_DELAY_MS;

describe("noticeWindow", () => {
  it("says nothing about a load that finishes before the delay", () => {
    // The landing hero: zero splats, so the only wait is renderer start-up.
    expect(noticeWindow({ loadStartedMs: T0, loadEndedMs: T0 + 120 })).toBeNull();
  });

  it("says nothing about a load that finishes exactly at the threshold", () => {
    expect(noticeWindow({ loadStartedMs: T0, loadEndedMs: APPEARS })).toBeNull();
  });

  it("goes up at the threshold and stays while the load runs", () => {
    const w = noticeWindow({ loadStartedMs: T0, loadEndedMs: null });
    expect(w).toEqual({
      appearsAtMs: APPEARS,
      hidesAtMs: Number.POSITIVE_INFINITY,
    });
  });

  it("holds the minimum when a load ends just past the threshold", () => {
    // Delay alone would trade a long flash for a 1 ms one.
    const w = noticeWindow({ loadStartedMs: T0, loadEndedMs: APPEARS + 1 });
    expect(w).not.toBeNull();
    expect(w!.hidesAtMs).toBe(APPEARS + NOTICE_MIN_VISIBLE_MS);
    expect(w!.hidesAtMs - w!.appearsAtMs).toBe(NOTICE_MIN_VISIBLE_MS);
  });

  it("comes down with the load once it has outlasted the minimum", () => {
    const ended = APPEARS + NOTICE_MIN_VISIBLE_MS + 500;
    const w = noticeWindow({ loadStartedMs: T0, loadEndedMs: ended });
    expect(w!.hidesAtMs).toBe(ended);
  });

  it("never shows for less than the minimum, over a swept range", () => {
    // The property the two constants exist to guarantee: no visible
    // window is shorter than the minimum, at any load duration.
    for (let dur = 0; dur <= 2000; dur += 7) {
      const w = noticeWindow({ loadStartedMs: T0, loadEndedMs: T0 + dur });
      if (w === null) continue;
      expect(w.hidesAtMs - w.appearsAtMs).toBeGreaterThanOrEqual(
        NOTICE_MIN_VISIBLE_MS,
      );
    }
  });

  it("shows for a load exactly when that load outruns the delay", () => {
    for (let dur = 0; dur <= 2000; dur += 7) {
      const shown = noticeWindow({ loadStartedMs: T0, loadEndedMs: T0 + dur });
      expect(shown !== null).toBe(dur > NOTICE_DELAY_MS);
    }
  });
});

describe("useLoadingNotice", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  /** Advance both the timer queue and the clock the hook measures with. */
  const advance = async (ms: number) => {
    await act(async () => {
      vi.advanceTimersByTime(ms);
    });
  };

  it("stays silent through a load that beats the delay", async () => {
    // The landing hero. Its whole load is renderer start-up.
    const { result, rerender } = renderHook(
      ({ loading }) => useLoadingNotice(loading),
      { initialProps: { loading: true } },
    );
    await advance(NOTICE_DELAY_MS - 50);
    expect(result.current).toBe(false);
    rerender({ loading: false });
    await advance(5000);
    expect(result.current).toBe(false);
  });

  it("appears once a load outruns the delay", async () => {
    const { result } = renderHook(
      ({ loading }) => useLoadingNotice(loading),
      { initialProps: { loading: true } },
    );
    expect(result.current).toBe(false);
    await advance(NOTICE_DELAY_MS - 1);
    expect(result.current).toBe(false);
    await advance(2);
    expect(result.current).toBe(true);
  });

  it("holds the minimum when the load ends right after it appears", async () => {
    const { result, rerender } = renderHook(
      ({ loading }) => useLoadingNotice(loading),
      { initialProps: { loading: true } },
    );
    await advance(NOTICE_DELAY_MS + 10);
    expect(result.current).toBe(true);
    rerender({ loading: false });
    await advance(NOTICE_MIN_VISIBLE_MS - 50);
    expect(result.current).toBe(true); // still held — no second flash
    await advance(100);
    expect(result.current).toBe(false);
  });

  it("comes down with the load once it has outlasted the minimum", async () => {
    const { result, rerender } = renderHook(
      ({ loading }) => useLoadingNotice(loading),
      { initialProps: { loading: true } },
    );
    await advance(NOTICE_DELAY_MS + NOTICE_MIN_VISIBLE_MS + 1000);
    expect(result.current).toBe(true);
    rerender({ loading: false });
    await advance(1);
    expect(result.current).toBe(false);
  });
});
