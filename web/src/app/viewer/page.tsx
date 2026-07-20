"use client";

/**
 * Developer splat viewer. The product path embeds the viewer in the room
 * page (RoomViewerPanel); this page is the workbench — hidden from the nav
 * in live mode. Sources, all funneling into the same PositionedSplat list:
 *
 *   /viewer?scene=<scene_id> — the room page's embedded flow, standalone.
 *   /viewer?url=<splat url>  — render a single splat file at origin.
 *   drag & drop a .ply/.spz/.splat/.ksplat file — same, from disk.
 *
 * With no source it tries /dev-fixtures/manifest.json (the synthetic room
 * from tools/make_synthetic_splat.py) and falls back to instructions.
 */

import { useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";

import RoomViewerPanel from "@/components/RoomViewerPanel";
import SplatViewer from "@/components/SplatViewer";
import {
  assembleScene,
  type FusedObject,
  type PositionedSplat,
  type SceneAssets,
} from "@/lib/api/types";

/** Async-only result, stamped with the source key it was loaded for — a
 * stale key renders as loading, so effects never set state synchronously
 * (react-hooks/set-state-in-effect). */
type Result =
  | { key: string; phase: "idle" } // no source; show instructions
  | {
      key: string;
      phase: "ready";
      splats: PositionedSplat[];
      unrenderable: FusedObject[];
    };

function singleSplat(key: string, url: string, label: string): Result {
  return {
    key,
    phase: "ready",
    unrenderable: [],
    splats: [
      { url, label, position: [0, 0.5, 0], rotation_xyzw: [0, 0, 0, 1], scale: 1 },
    ],
  };
}

function DevViewerContent({ directUrl }: { directUrl: string | null }) {
  const key = directUrl ?? "";
  const [result, setResult] = useState<Result | null>(null);
  const state: Result | { phase: "loading" } =
    result && result.key === key ? result : { phase: "loading" };

  useEffect(() => {
    let cancelled = false;

    async function load() {
      if (directUrl) {
        setResult(singleSplat(key, directUrl, "splat"));
        return;
      }
      // No source: try the local dev fixture manifest.
      try {
        const resp = await fetch("/dev-fixtures/manifest.json");
        if (!resp.ok) throw new Error("no fixture");
        const assets = (await resp.json()) as SceneAssets;
        if (cancelled) return;
        const { splats, unrenderable } = assembleScene(assets);
        setResult(
          splats.length
            ? { key, phase: "ready", splats, unrenderable }
            : { key, phase: "idle" },
        );
      } catch {
        if (!cancelled) setResult({ key, phase: "idle" });
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, [key, directUrl]);

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      const file = e.dataTransfer.files[0];
      if (!file) return;
      setResult(singleSplat(key, URL.createObjectURL(file), file.name));
    },
    [key],
  );

  return (
    <div onDrop={onDrop} onDragOver={(e) => e.preventDefault()}>
      {state.phase === "loading" && (
        <div className="mt-8 h-[62vh] animate-pulse rounded-2xl border border-white/[0.06] bg-white/[0.02]" />
      )}

      {state.phase === "idle" && (
        <div className="mt-8 flex h-[62vh] flex-col items-center justify-center rounded-2xl border border-dashed border-white/15 bg-white/[0.02] text-center">
          <p className="text-zinc-300">Drop a splat file to view it</p>
          <p className="mt-2 max-w-sm text-sm leading-relaxed text-zinc-500">
            .ply, .spz, .splat or .ksplat — or generate the synthetic room
            fixture with <code className="font-mono text-xs">tools/make_synthetic_splat.py</code>.
          </p>
        </div>
      )}

      {state.phase === "ready" && (
        <>
          <SplatViewer splats={state.splats} className="mt-8 h-[62vh]" />
          {state.unrenderable.length > 0 && (
            <p className="mt-3 text-sm text-zinc-500">
              Not shown:{" "}
              {state.unrenderable
                .map((o) => `${o.label} (${o.reason ?? "no transform"})`)
                .join(", ")}
            </p>
          )}
        </>
      )}
    </div>
  );
}

function ViewerContent() {
  const params = useSearchParams();
  const sceneId = params.get("scene");
  const directUrl = params.get("url");

  return (
    <div>
      <div className="flex items-baseline justify-between">
        <h1 className="text-3xl font-semibold tracking-tight">Viewer</h1>
        <span className="font-mono text-[10px] text-zinc-600">dev workbench</span>
      </div>
      {sceneId ? (
        <div className="mt-8">
          <RoomViewerPanel sceneId={sceneId} className="h-[62vh]" />
        </div>
      ) : (
        <DevViewerContent directUrl={directUrl} />
      )}
    </div>
  );
}

export default function ViewerPage() {
  return (
    <div className="mx-auto max-w-6xl px-6 py-14">
      <Suspense
        fallback={
          <div className="h-[62vh] animate-pulse rounded-2xl bg-white/[0.02]" />
        }
      >
        <ViewerContent />
      </Suspense>
    </div>
  );
}
