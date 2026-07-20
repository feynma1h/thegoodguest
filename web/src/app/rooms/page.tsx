"use client";

/**
 * Room browser: GET /scenes rendered as a card grid. Client-side fetch —
 * the static export has no server; data loads after hydration through the
 * ApiClient (mock fixtures or live api-public depending on mode).
 */

import { useEffect, useState } from "react";

import RoomCard from "@/components/RoomCard";
import { PillLink } from "@/components/ui/spring";
import { getApiClient } from "@/lib/api";
import { ApiError } from "@/lib/api/client";
import type { SceneSummary } from "@/lib/api/types";

type State =
  | { phase: "loading" }
  | { phase: "error"; message: string }
  | { phase: "ready"; scenes: SceneSummary[] };

export default function RoomsPage() {
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
    <div className="mx-auto max-w-6xl px-6 py-14">
      <div className="flex items-baseline justify-between">
        <h1 className="text-3xl font-semibold tracking-tight">Your rooms</h1>
        {state.phase === "ready" && state.scenes.length > 0 && (
          <span className="text-sm text-zinc-500">
            {state.scenes.length} {state.scenes.length === 1 ? "room" : "rooms"}
          </span>
        )}
      </div>

      {state.phase === "loading" && (
        <div className="mt-10 grid gap-5 sm:grid-cols-2">
          {[0, 1, 2, 3].map((i) => (
            <div
              key={i}
              className="h-40 animate-pulse rounded-2xl border border-white/[0.06] bg-white/[0.02]"
            />
          ))}
        </div>
      )}

      {state.phase === "error" && (
        <div className="mt-10 rounded-2xl border border-red-500/20 bg-red-500/5 p-6">
          <p className="text-sm font-medium text-red-300">Couldn&apos;t load your rooms</p>
          <p className="mt-1 text-sm text-zinc-400">{state.message}</p>
        </div>
      )}

      {state.phase === "ready" && state.scenes.length === 0 && (
        <div className="mt-24 flex flex-col items-center text-center">
          <p className="text-xl font-medium text-zinc-200">No rooms yet.</p>
          <p className="mt-3 max-w-sm text-sm leading-relaxed text-zinc-500">
            Your first scan takes about a minute — a slow walk around the room
            with your iPhone.
          </p>
          <PillLink href="/new" className="mt-8">
            Scan your first room
          </PillLink>
        </div>
      )}

      {state.phase === "ready" && state.scenes.length > 0 && (
        <div className="mt-10 grid gap-5 sm:grid-cols-2">
          {state.scenes.map((scene) => (
            <RoomCard key={scene.scene_id} scene={scene} />
          ))}
        </div>
      )}
    </div>
  );
}
