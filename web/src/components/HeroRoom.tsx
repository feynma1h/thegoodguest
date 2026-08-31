"use client";

/**
 * The landing hero's stage: a real room measuring itself.
 *
 * This is the hero image (decision 0122) — not a picture of a room, but
 * the first two movements of the reveal (decision 0097) played against a
 * real capture's geometry: the measured boundary drawing itself, then the
 * surfaces materializing in place. No object splats, by design — see
 * lib/heroRoom for why, and do not add them back here.
 *
 * The component coordinates NOTHING with the page. The copy beside it
 * enters on its own stagger from the first frame and never waits on the
 * reveal, so a slow GPU, a stalled fetch or a fixture that cannot be read
 * costs a visitor the room and not the words. A hero that fails is a page
 * with no picture; it is never a page with nothing to read.
 *
 * SplatViewer stays the only module that touches three.js; this file
 * speaks ShellPlane/PositionedSplat like everything else.
 */

import { useEffect, useState } from "react";

import SplatViewer from "@/components/SplatViewer";
import { GuestLine } from "@/components/ui/voice";
import type { AssembledScene } from "@/lib/api/types";
import { type HeroVariant, loadHeroScene } from "@/lib/heroRoom";

export default function HeroRoom({
  variant = "a",
  className,
}: {
  variant?: HeroVariant;
  className?: string;
}) {
  const [scene, setScene] = useState<AssembledScene | null>(null);
  const [failed, setFailed] = useState(false);
  const [arrival, setArrival] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    loadHeroScene(variant)
      .then((loaded) => {
        if (cancelled) return;
        if (!loaded) {
          setFailed(true);
          return;
        }
        setScene(loaded);
      })
      .catch(() => {
        if (cancelled) return;
        setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [variant]);

  if (failed) return null;

  return (
    <div
      className={`relative min-h-[62vh] overflow-hidden rounded-xl border border-ink/15 lg:min-h-[420px] ${className ?? ""}`}
      // The stage exists from the first paint, before the fixture has even
      // been read, so the copy arrives beside a room already dark and
      // waiting rather than beside a hole where one will be. Same
      // atmosphere SplatViewer paints, so the handover is invisible.
      style={{
        background:
          "radial-gradient(120% 90% at 50% 42%, #36342f 0%, #23221e 55%, #181715 100%)",
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
