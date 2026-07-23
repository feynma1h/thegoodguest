"use client";

/**
 * Workbench viewer for a ready room: fetches the scene's assets,
 * assembles the positioned-splat list, and renders SplatViewer with a
 * plain inventory below. Used by the /viewer dev page's ?scene= path.
 * The product path is RoomStage (immersive, with the reveal); this
 * panel is the same assets → assembled-room flow without choreography —
 * a workbench, not a moment.
 */

import { useEffect, useState } from "react";

import SplatViewer from "@/components/SplatViewer";
import { getApiClient } from "@/lib/api";
import { ApiError, SceneNotReadyError } from "@/lib/api/client";
import {
  assembleScene,
  type FusedObject,
  type PositionedSplat,
  type ShellPlane,
} from "@/lib/api/types";
import { statusMeta } from "@/lib/status";

type Result =
  | { forScene: string; phase: "not_ready"; message: string }
  | { forScene: string; phase: "error"; message: string }
  | {
      forScene: string;
      phase: "ready";
      splats: PositionedSplat[];
      shell: ShellPlane[] | null;
      unrenderable: FusedObject[];
    };

function Inventory({
  splats,
  unrenderable,
}: {
  splats: PositionedSplat[];
  unrenderable: FusedObject[];
}) {
  return (
    <div>
      <h3 className="text-xs font-medium text-ink/50">In this room</h3>
      <ul className="mt-3 space-y-2">
        {splats.map((s, i) => (
          <li key={`${s.label}-${i}`} className="flex items-center justify-between text-sm">
            <span className="capitalize text-ink/85">{s.label}</span>
            <span className="text-xs text-ink/40">placed</span>
          </li>
        ))}
        {unrenderable.map((o) => (
          <li
            key={o.object_id}
            className="flex items-center justify-between text-sm"
            title={`Seen but not yet placed (${o.reason ?? "no transform"})`}
          >
            <span className="capitalize text-ink/45">{o.label}</span>
            <span className="text-xs text-ink/40">seen</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function RoomViewerPanel({
  sceneId,
  className,
}: {
  sceneId: string;
  className?: string;
}) {
  const [result, setResult] = useState<Result | null>(null);
  const state =
    result && result.forScene === sceneId ? result : { phase: "loading" as const };

  useEffect(() => {
    let cancelled = false;
    getApiClient()
      .getSceneAssets(sceneId)
      .then((assets) => {
        if (cancelled) return;
        const { splats, shell, unrenderable } = assembleScene(assets);
        setResult({ forScene: sceneId, phase: "ready", splats, shell, unrenderable });
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
        className={`animate-pulse rounded-xl border border-ink/10 bg-parchment/60 ${className ?? "h-[62vh]"}`}
      />
    );
  }
  if (state.phase === "not_ready" || state.phase === "error") {
    return (
      <div
        className={`flex items-center justify-center rounded-xl border border-ink/15 bg-parchment/40 p-8 text-center ${className ?? "h-[62vh]"}`}
      >
        <p className="max-w-sm text-sm leading-relaxed text-ink/60">{state.message}</p>
      </div>
    );
  }

  return (
    <div>
      <SplatViewer
        splats={state.splats}
        shell={state.shell}
        className={className ?? "h-[62vh]"}
      />
      <div className="mt-6">
        <Inventory splats={state.splats} unrenderable={state.unrenderable} />
      </div>
    </div>
  );
}
