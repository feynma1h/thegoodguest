"use client";

/**
 * Embedded viewer for a ready room: fetches the scene's assets, assembles
 * the positioned-splat list, and renders SplatViewer inline with a quiet
 * inventory of what was found. Used by the room page (primary) and the
 * /viewer dev page's ?scene= path — one implementation of the
 * assets → assembled-room flow.
 */

import { useEffect, useState } from "react";

import SplatViewer from "@/components/SplatViewer";
import { getApiClient } from "@/lib/api";
import { ApiError, SceneNotReadyError } from "@/lib/api/client";
import {
  assembleScene,
  type FusedObject,
  type PositionedSplat,
} from "@/lib/api/types";
import { statusMeta } from "@/lib/status";

type Result =
  | { forScene: string; phase: "not_ready"; message: string }
  | { forScene: string; phase: "error"; message: string }
  | {
      forScene: string;
      phase: "ready";
      splats: PositionedSplat[];
      unrenderable: FusedObject[];
    };

export default function RoomViewerPanel({
  sceneId,
  className,
}: {
  sceneId: string;
  className?: string;
}) {
  const [result, setResult] = useState<Result | null>(null);
  const state = result && result.forScene === sceneId ? result : { phase: "loading" as const };

  useEffect(() => {
    let cancelled = false;
    getApiClient()
      .getSceneAssets(sceneId)
      .then((assets) => {
        if (cancelled) return;
        const { splats, unrenderable } = assembleScene(assets);
        setResult({ forScene: sceneId, phase: "ready", splats, unrenderable });
      })
      .catch((exc: unknown) => {
        if (cancelled) return;
        if (exc instanceof SceneNotReadyError) {
          setResult({
            forScene: sceneId,
            phase: "not_ready",
            message: statusMeta(exc.sceneStatus).description,
          });
        } else {
          setResult({
            forScene: sceneId,
            phase: "error",
            message:
              exc instanceof ApiError ? exc.message : "Could not load this room.",
          });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [sceneId]);

  if (state.phase === "loading") {
    return (
      <div
        className={`animate-pulse rounded-2xl border border-white/[0.06] bg-white/[0.02] ${className ?? ""}`}
      />
    );
  }
  if (state.phase === "not_ready" || state.phase === "error") {
    return (
      <div
        className={`flex items-center justify-center rounded-2xl border border-white/[0.06] bg-white/[0.02] p-8 text-center ${className ?? ""}`}
      >
        <p className="max-w-sm text-sm leading-relaxed text-zinc-400">{state.message}</p>
      </div>
    );
  }

  return (
    <div>
      <SplatViewer splats={state.splats} className={className ?? "h-[60vh]"} />
      <div className="mt-4 flex flex-wrap items-center gap-2">
        <span className="mr-1 font-mono text-[10px] uppercase tracking-widest text-zinc-600">
          Found in this room
        </span>
        {state.splats.map((s, i) => (
          <span
            key={`${s.label}-${i}`}
            className="rounded-full border border-white/[0.08] bg-white/[0.03] px-3 py-1 text-xs text-zinc-300"
          >
            {s.label}
          </span>
        ))}
        {state.unrenderable.map((o) => (
          <span
            key={o.object_id}
            className="rounded-full border border-dashed border-white/[0.08] px-3 py-1 text-xs text-zinc-600"
            title={`Seen but not yet placed (${o.reason ?? "no transform"})`}
          >
            {o.label}
          </span>
        ))}
      </div>
    </div>
  );
}
