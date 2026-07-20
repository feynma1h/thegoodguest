"use client";

/**
 * Scene browser: GET /scenes rendered as a card grid. Client-side fetch —
 * the static export has no server; data loads after hydration through the
 * ApiClient (mock fixtures or live api-public depending on mode).
 */

import { useEffect, useState } from "react";

import SceneCard from "@/components/SceneCard";
import { getApiClient } from "@/lib/api";
import { ApiError } from "@/lib/api/client";
import type { SceneSummary } from "@/lib/api/types";

type State =
  | { phase: "loading" }
  | { phase: "error"; message: string }
  | { phase: "ready"; scenes: SceneSummary[] };

export default function ScenesPage() {
  const [state, setState] = useState<State>({ phase: "loading" });

  useEffect(() => {
    let cancelled = false;
    getApiClient()
      .listScenes()
      .then((scenes) => !cancelled && setState({ phase: "ready", scenes }))
      .catch((exc: unknown) => {
        if (cancelled) return;
        const message =
          exc instanceof ApiError ? exc.message : "Could not reach the server.";
        setState({ phase: "error", message });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div>
      <div className="flex items-baseline justify-between">
        <h1 className="text-2xl font-semibold tracking-tight">Your scenes</h1>
        {state.phase === "ready" && (
          <span className="text-sm text-zinc-500">
            {state.scenes.length} {state.scenes.length === 1 ? "room" : "rooms"}
          </span>
        )}
      </div>

      {state.phase === "loading" && (
        <div className="mt-8 grid gap-4 sm:grid-cols-2">
          {[0, 1, 2, 3].map((i) => (
            <div
              key={i}
              className="h-28 animate-pulse rounded-xl border border-zinc-800 bg-zinc-900/40"
            />
          ))}
        </div>
      )}

      {state.phase === "error" && (
        <div className="mt-8 rounded-xl border border-red-500/20 bg-red-500/5 p-6">
          <p className="text-sm font-medium text-red-300">Couldn&apos;t load scenes</p>
          <p className="mt-1 text-sm text-zinc-400">{state.message}</p>
        </div>
      )}

      {state.phase === "ready" && state.scenes.length === 0 && (
        <div className="mt-8 rounded-xl border border-zinc-800 bg-zinc-900/40 p-10 text-center">
          <p className="text-zinc-300">No rooms yet.</p>
          <p className="mt-2 text-sm text-zinc-500">
            Capture one with the iOS app and it will appear here.
          </p>
        </div>
      )}

      {state.phase === "ready" && state.scenes.length > 0 && (
        <div className="mt-8 grid gap-4 sm:grid-cols-2">
          {state.scenes.map((scene) => (
            <SceneCard key={scene.scene_id} scene={scene} />
          ))}
        </div>
      )}
    </div>
  );
}
