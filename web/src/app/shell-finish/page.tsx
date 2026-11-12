"use client";

/**
 * Local-only shell finish preview (lib/shellFinish). Loads a room's
 * shell.json and the finish tools/shell_finish.py derived from it — both
 * from a local server (tools/serve_scene.py) so real captures never sit
 * under public/ — and renders the walls and floor as the designed finish.
 *
 *   /shell-finish?shell=<url>&finish=<url>
 *     &furniture=<url>  furniture twins (tools/furniture_models.py -> furniture.json)
 *     &furniture=0    leave the twins out
 *     &mode=night     open the room at night (twins only)
 *     &look=photo     keep the light the render-vs-photo loop is calibrated in
 *     &plain=1        the flat measured shell, for an A/B
 *     &exposure=1.6   override the finish's colour gain while calibrating
 *     &still=1        the room's still picture (services/scene-finish /still):
 *                     the first corner view, edge to edge, with no controls
 *                     or note — a bare shell included
 *
 * Inert unless NEXT_PUBLIC_SHELL_FINISH=1 (set it for `next dev`; a
 * production build leaves it unset, so this page renders nothing useful).
 */

import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";

import SplatViewer from "@/components/SplatViewer";
import { assembleScene, type PositionedSplat, type SceneAssets, type ShellPlane } from "@/lib/api/types";
import { parseFurniture, type FurnitureBundle } from "@/lib/furniture";
import { parseFinish, shellFinishPreviewEnabled, type ShellFinish } from "@/lib/shellFinish";

type Loaded =
  | { key: string; phase: "ready"; shell: ShellPlane[]; splats: PositionedSplat[]; finish: ShellFinish | null; furniture: FurnitureBundle | null; note: string }
  | { key: string; phase: "error"; note: string };

function Preview() {
  const params = useSearchParams();
  const shellUrl = params.get("shell");
  const finishUrl = params.get("finish");
  const furnitureUrl = params.get("furniture");
  const noFurniture = params.get("furniture") === "0";
  // ?assets=<url>: an assets-shaped doc (manifest placements + signed/local
  // splat urls), so splat clip boxes can steer the staging.
  const assetsUrl = params.get("assets");
  const plain = params.get("plain") === "1";
  const exposure = params.get("exposure");
  const look = params.get("look");
  const mode = params.get("mode");
  const still = params.get("still") === "1";
  const key =`${shellUrl}|${finishUrl}|${assetsUrl}|${furnitureUrl}|${look}|${mode}`;
  const [loaded, setLoaded] = useState<Loaded | null>(null);

  useEffect(() => {
    if (!shellUrl) return;
    let cancelled = false;
    (async () => {
      try {
        const doc = await (await fetch(shellUrl)).json();
        // A bare shell.json, or an assets response carrying `shell`.
        const shellDoc = doc && "walls" in doc ? doc : doc.shell;
        const { shell } = assembleScene({
          scene_id: shellDoc?.scene_id ?? "local",
          manifest: { objects: [] },
          asset_urls: {},
          shell: shellDoc,
        } as unknown as SceneAssets);
        if (!shell) throw new Error("shell is not ready or has no planes");
        let splats: PositionedSplat[] = [];
        if (assetsUrl) {
          const assets = (await (await fetch(assetsUrl)).json()) as SceneAssets;
          splats = assembleScene(assets).splats;
        }
        let finish: ShellFinish | null = null;
        let note = "flat shell (no finish file)";
        if (finishUrl) {
          const raw = await (await fetch(finishUrl)).json();
          const wallCount = shell.filter((p) => p.kind === "wall").length;
          finish = parseFinish(raw, wallCount);
          note = finish
            ? "finish drawn"
            : `finish file does not fit this shell (${wallCount} walls) — showing the flat shell`;
        }
        let furniture: FurnitureBundle | null = null;
        if (furnitureUrl && !noFurniture) {
          furniture = parseFurniture(await (await fetch(furnitureUrl)).json());
          if (furniture && look === "photo") furniture.look = "photo";
          if (furniture && mode === "night") furniture.mode = "night";
          note += furniture ? `; ${furniture.objects.length} furniture twins` : "; furniture file not understood";
        }
        if (!cancelled) setLoaded({ key, phase: "ready", shell, splats, finish, furniture, note });
      } catch (e) {
        if (!cancelled)
          setLoaded({ key, phase: "error", note: e instanceof Error ? e.message : String(e) });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [key, shellUrl, finishUrl, assetsUrl, furnitureUrl, noFurniture, look, mode]);

  const state = loaded && loaded.key === key ? loaded : null;
  const finish = useMemo(() => {
    if (!state || state.phase !== "ready" || plain || !state.finish) return null;
    const e = exposure ? Number(exposure) : undefined;
    return e && e > 0 ? { ...state.finish, exposure: e } : state.finish;
  }, [state, plain, exposure]);

  if (!shellFinishPreviewEnabled())
    return <p className="p-8 text-sm text-ink/55">Shell finish preview is off in this build.</p>;
  if (!shellUrl)
    return (
      <p className="p-8 text-sm text-ink/55">
        Give <code>?shell=&lt;url&gt;&amp;finish=&lt;url&gt;</code> — see tools/serve_scene.py.
      </p>
    );
  if (!state) return <div className="h-screen animate-pulse bg-parchment/60" />;
  if (state.phase === "error") return <p className="p-8 text-sm text-ink/55">{state.note}</p>;
  return (
    <div className="fixed inset-0 z-50">
      <SplatViewer
        splats={state.splats}
        shell={state.shell}
        finish={finish}
        furniture={state.furniture}
        className="h-full w-full"
        frameless={still}
        still={still}
      />
      {!still && (
        <span className="pointer-events-none absolute left-3 top-3 font-mono text-[10px] text-ink/35">
          {plain ? "flat shell (plain=1)" : state.note}
        </span>
      )}
    </div>
  );
}

export default function ShellFinishPage() {
  return (
    <Suspense fallback={<div className="h-screen animate-pulse bg-parchment/60" />}>
      <Preview />
    </Suspense>
  );
}
