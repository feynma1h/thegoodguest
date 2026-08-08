"use client";

/**
 * The landing hero's stage: a real room measuring itself.
 *
 * This is the hero image (decision 0126) — not a picture of a room, but
 * the first two movements of the reveal (decision 0097) played against a
 * real capture's geometry: the measured boundary drawing itself, then the
 * surfaces materializing in place. No object splats, by design — see
 * lib/heroRoom for why, and do not add them back here.
 *
 * The component owns exactly one piece of coordination: it tells the page
 * when the room has settled, so the copy can land in the quiet beat the
 * score already provides. That signal is guaranteed to arrive — from the
 * reveal, from the reduced-motion path (which fires it at once, because
 * nothing pretends to have materialized), from a fixture that failed to
 * load, or from a bounded fallback timer. A landing page must never be
 * left wordless by a renderer.
 *
 * SplatViewer stays the only module that touches three.js; this file
 * speaks ShellPlane/PositionedSplat like everything else.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import SplatViewer from "@/components/SplatViewer";
import { GuestLine } from "@/components/ui/voice";
import type { AssembledScene } from "@/lib/api/types";
import {
  HERO_COPY_FALLBACK_MS,
  type HeroVariant,
  loadHeroScene,
} from "@/lib/heroRoom";

export default function HeroRoom({
  variant = "a",
  onSettled,
  className,
}: {
  variant?: HeroVariant;
  /** The room has finished assembling (or will never start) — land the
   * copy. Fires exactly once. */
  onSettled: () => void;
  className?: string;
}) {
  const [scene, setScene] = useState<AssembledScene | null>(null);
  const [failed, setFailed] = useState(false);
  const [arrival, setArrival] = useState<string | null>(null);

  // Fires once, whoever gets there first — the reveal, the failure path,
  // or the fallback timer.
  const settledRef = useRef(false);
  const onSettledRef = useRef(onSettled);
  useEffect(() => {
    onSettledRef.current = onSettled;
  });
  const settle = useCallback(() => {
    if (settledRef.current) return;
    settledRef.current = true;
    onSettledRef.current();
  }, []);

  useEffect(() => {
    let cancelled = false;
    loadHeroScene(variant)
      .then((loaded) => {
        if (cancelled) return;
        if (!loaded) {
          setFailed(true);
          settle();
          return;
        }
        setScene(loaded);
      })
      .catch(() => {
        if (cancelled) return;
        setFailed(true);
        settle();
      });
    return () => {
      cancelled = true;
    };
  }, [variant, settle]);

  // The ceiling. The reveal normally beats this by seconds; it exists so a
  // renderer that never reports cannot hold the copy hostage.
  useEffect(() => {
    const timer = window.setTimeout(settle, HERO_COPY_FALLBACK_MS);
    return () => window.clearTimeout(timer);
  }, [settle]);

  if (failed) return null;

  return (
    <div
      className={`relative min-h-[62vh] overflow-hidden rounded-xl border border-ink/15 lg:min-h-[420px] ${className ?? ""}`}
      // The stage exists from the first paint, before the fixture has even
      // been read — otherwise the landing page's first frame is blank
      // parchment with no copy yet, which reads as broken rather than as a
      // room about to measure itself. Same atmosphere SplatViewer paints,
      // so the handover is invisible.
      style={{
        background:
          "radial-gradient(120% 90% at 50% 42%, #3f3226 0%, #2a2017 55%, #1c1610 100%)",
      }}
    >
      {scene && (
        <SplatViewer
          splats={scene.splats}
          shell={scene.shell}
          reveal
          idleOrbit
          frameless
          className="h-full min-h-[62vh] lg:min-h-[420px]"
          onRevealStep={(_, label) => setArrival(label)}
          onRevealCaptionsDone={() => setArrival(null)}
          onRevealDone={settle}
        />
      )}
      {arrival && (
        <div className="pointer-events-none absolute bottom-5 left-5 max-w-[320px] rounded-xl bg-paper/95 p-4 shadow-float">
          <GuestLine className="text-[14.5px]">
            The {arrival} — scanned, not modelled. The dents came along too.
          </GuestLine>
        </div>
      )}
    </div>
  );
}
