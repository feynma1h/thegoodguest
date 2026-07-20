"use client";

/**
 * The landing page's live room — the product demonstrating itself. Loads
 * the dev fixture manifest (tools/make_synthetic_splat.py output) and
 * renders it as an interactive, idly-orbiting scene; the section renders
 * nothing at all when no manifest is present, so a deploy without a demo
 * room simply has no demo section rather than a broken one.
 *
 * LAUNCH NOTE: /dev-fixtures/ is gitignored — the deployed landing page
 * hides this section until a curated real-room capture replaces the
 * synthetic fixture as the shipped demo.
 */

import { motion } from "motion/react";
import { useEffect, useState } from "react";

import SplatViewer from "@/components/SplatViewer";
import {
  assembleScene,
  type PositionedSplat,
  type SceneAssets,
} from "@/lib/api/types";

export default function DemoRoom() {
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
        // No demo room available — section stays hidden.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (!splats) return null;

  return (
    <section className="border-t border-white/[0.06]">
      <div className="mx-auto max-w-6xl px-6 py-24">
        <motion.div
          initial={{ opacity: 0, y: 24 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-80px" }}
          transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
        >
          <h2 className="text-2xl font-semibold tracking-tight sm:text-3xl">
            A scan, not a photograph.
          </h2>
          <p className="mt-3 max-w-lg text-sm leading-relaxed text-zinc-400">
            Every object below was rebuilt in 3D from a scan and placed where
            it actually stood. Grab it and look around.
          </p>
        </motion.div>
        <motion.div
          initial={{ opacity: 0, y: 32 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-60px" }}
          transition={{ duration: 0.7, ease: [0.22, 1, 0.36, 1], delay: 0.1 }}
          className="mt-8"
        >
          <SplatViewer splats={splats} idleOrbit className="h-[64vh]" />
        </motion.div>
      </div>
    </section>
  );
}
