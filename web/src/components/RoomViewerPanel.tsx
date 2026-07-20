"use client";

/**
 * Embedded viewer for a ready room: fetches the scene's assets, assembles
 * the positioned-splat list, and renders SplatViewer inline. Used by the
 * room page (primary) and the /viewer dev page's ?scene= path — one
 * implementation of the assets → assembled-room flow.
 *
 * Layout: pass `rail` to get the room page's two-column structure —
 * viewer left, a side rail right carrying the caller's sections followed
 * by this panel's object inventory. The rail is deliberately the room
 * page's growth surface: analysis today, the conversational interface
 * when it lands (decision 0056). Without `rail`, the viewer renders
 * full-width with the inventory below (dev viewer).
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

function Inventory({
  splats,
  unrenderable,
}: {
  splats: PositionedSplat[];
  unrenderable: FusedObject[];
}) {
  return (
    <div>
      <h3 className="text-xs font-medium text-zinc-500">In this room</h3>
      <ul className="mt-3 space-y-2">
        {splats.map((s, i) => (
          <li key={`${s.label}-${i}`} className="flex items-center justify-between text-sm">
            <span className="capitalize text-zinc-200">{s.label}</span>
            <span className="text-xs text-zinc-600">placed</span>
          </li>
        ))}
        {unrenderable.map((o) => (
          <li
            key={o.object_id}
            className="flex items-center justify-between text-sm"
            title={`Seen but not yet placed (${o.reason ?? "no transform"})`}
          >
            <span className="capitalize text-zinc-500">{o.label}</span>
            <span className="text-xs text-zinc-600">seen</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function RoomViewerPanel({
  sceneId,
  className,
  rail,
}: {
  sceneId: string;
  className?: string;
  rail?: React.ReactNode;
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
        className={`animate-pulse rounded-2xl border border-white/[0.06] bg-white/[0.02] ${className ?? "h-[62vh]"}`}
      />
    );
  }
  if (state.phase === "not_ready" || state.phase === "error") {
    return (
      <div
        className={`flex items-center justify-center rounded-2xl border border-white/[0.06] bg-white/[0.02] p-8 text-center ${className ?? "h-[62vh]"}`}
      >
        <p className="max-w-sm text-sm leading-relaxed text-zinc-400">{state.message}</p>
      </div>
    );
  }

  if (rail !== undefined) {
    return (
      <div className="grid gap-8 lg:grid-cols-[1fr_300px]">
        <SplatViewer splats={state.splats} className={className ?? "h-[62vh]"} />
        <aside className="flex flex-col gap-8">
          {rail}
          <Inventory splats={state.splats} unrenderable={state.unrenderable} />
        </aside>
      </div>
    );
  }

  return (
    <div>
      <SplatViewer splats={state.splats} className={className ?? "h-[62vh]"} />
      <div className="mt-6">
        <Inventory splats={state.splats} unrenderable={state.unrenderable} />
      </div>
    </div>
  );
}
