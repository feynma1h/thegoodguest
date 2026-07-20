"use client";

/**
 * The landing page's live room — the product demonstrating itself. Loads
 * the dev fixture manifest (tools/make_synthetic_splat.py output) and
 * renders it as the hero's only image: an interactive, idly-orbiting
 * scene with the guest's caption floating over it. When no manifest is
 * present the hook returns null and the hero simply has no demo panel,
 * rather than a broken one.
 *
 * LAUNCH NOTE: /dev-fixtures/ is gitignored — the deployed landing page
 * hides the demo until a curated real-room capture replaces the
 * synthetic fixture as the shipped demo.
 */

import { useEffect, useState } from "react";

import SplatViewer from "@/components/SplatViewer";
import { GuestLine } from "@/components/ui/voice";
import {
  assembleScene,
  type PositionedSplat,
  type SceneAssets,
} from "@/lib/api/types";

/** Fixture loader shared by whoever presents the demo. Null until loaded;
 * stays null when no fixture is deployed. */
export function useDemoSplats(): PositionedSplat[] | null {
  const [splats, setSplats] = useState<PositionedSplat[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const resp = await fetch("/dev-fixtures/manifest.json");
        if (!resp.ok) return;
        const assets = (await resp.json()) as SceneAssets;
        const { splats } = assembleScene(assets);
        if (!cancelled && splats.length > 0) setSplats(splats);
      } catch {
        // No demo room available — the demo simply doesn't exist.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return splats;
}

/** The hero's demo stage: the orbiting room with the guest's caption.
 * Fills its parent; the caption claims only what is true of the fixture. */
export default function DemoPanel({ splats }: { splats: PositionedSplat[] }) {
  return (
    <div className="relative h-full w-full">
      <SplatViewer splats={splats} idleOrbit className="h-full min-h-[420px]" />
      <div className="absolute bottom-5 left-5 max-w-[360px] rounded-xl bg-paper/95 p-4 shadow-float">
        <GuestLine className="text-[14.5px]">
          Every piece in this room was scanned, not modeled — the dents came
          along too. Have a look around.
        </GuestLine>
        <p className="mt-1.5 text-[11.5px] text-ink/55">
          the live demo room — drag to orbit
        </p>
      </div>
    </div>
  );
}
