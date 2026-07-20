"use client";

/**
 * A single room: /room?bundle=<bundle_id>. Query-param routing because the
 * static export cannot prerender unknown dynamic path segments
 * (useSearchParams requires the Suspense boundary below during prerender).
 *
 * When the room is ready the 3D space is embedded HERE — the room page is
 * the destination, not a status card pointing elsewhere. It renders as
 * viewer + side rail; the rail carries analysis today and is the
 * conversational interface's future home (decision 0056). While
 * processing, the copy narrates the analysis (with real 10s polling)
 * rather than exposing pipeline states.
 */

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import RoomViewerPanel from "@/components/RoomViewerPanel";
import StatusBadge from "@/components/StatusBadge";
import { getApiClient } from "@/lib/api";
import { ApiError } from "@/lib/api/client";
import type { SceneSummary } from "@/lib/api/types";
import { statusMeta } from "@/lib/status";

type Result =
  | { forBundle: string; phase: "error"; message: string }
  | { forBundle: string; phase: "ready"; scene: SceneSummary };

function RoomDetail() {
  const bundleId = useSearchParams().get("bundle");
  const [result, setResult] = useState<Result | null>(null);

  const state: Result | { phase: "loading" } | { phase: "missing" } = !bundleId
    ? { phase: "missing" }
    : result && result.forBundle === bundleId
      ? result
      : { phase: "loading" };

  useEffect(() => {
    if (!bundleId) return;
    let cancelled = false;
    let timer: number | undefined;
    // Poll while the room is in flight so "this page updates when the room
    // is ready" is actually true; stops on terminal states.
    const load = () => {
      getApiClient()
        .getSceneByBundle(bundleId)
        .then((scene) => {
          if (cancelled) return;
          setResult({ forBundle: bundleId, phase: "ready", scene });
          if (!statusMeta(scene.status).terminal) {
            timer = window.setTimeout(load, 10_000);
          }
        })
        .catch((exc: unknown) => {
          if (cancelled) return;
          const message =
            exc instanceof ApiError ? exc.message : "Could not reach the server.";
          setResult({ forBundle: bundleId, phase: "error", message });
        });
    };
    load();
    return () => {
      cancelled = true;
      if (timer !== undefined) clearTimeout(timer);
    };
  }, [bundleId]);

  if (state.phase === "missing") {
    return (
      <p className="text-zinc-400">
        No room selected.{" "}
        <Link href="/rooms" className="text-foreground underline underline-offset-4">
          Back to your rooms
        </Link>
      </p>
    );
  }
  if (state.phase === "loading") {
    return (
      <div className="h-48 animate-pulse rounded-2xl border border-white/[0.06] bg-white/[0.02]" />
    );
  }
  if (state.phase === "error") {
    return (
      <div className="rounded-2xl border border-red-500/20 bg-red-500/5 p-6">
        <p className="text-sm font-medium text-red-300">Couldn&apos;t load this room</p>
        <p className="mt-1 text-sm text-zinc-400">{state.message}</p>
      </div>
    );
  }

  const { scene } = state;
  const meta = statusMeta(scene.status);
  const captured = new Date(scene.created_at);
  const capturedDay = captured.toLocaleDateString(undefined, {
    month: "long",
    day: "numeric",
  });

  return (
    <div>
      <Link
        href="/rooms"
        className="text-sm text-zinc-500 transition-colors hover:text-zinc-300"
      >
        ← Your rooms
      </Link>

      <div className="mt-6 flex flex-wrap items-baseline justify-between gap-4">
        <h1 className="text-3xl font-semibold tracking-tight">Room · {capturedDay}</h1>
        <StatusBadge status={scene.status} />
      </div>

      {scene.status === "ready" ? (
        <div className="mt-8">
          <RoomViewerPanel
            sceneId={scene.scene_id}
            className="h-[62vh]"
            rail={
              <div className="border-b border-white/[0.06] pb-8">
                <h3 className="text-xs font-medium text-zinc-500">Captured</h3>
                <p className="mt-2 text-sm text-zinc-200">
                  {captured.toLocaleString(undefined, {
                    month: "long",
                    day: "numeric",
                    hour: "numeric",
                    minute: "2-digit",
                  })}
                </p>
                <p className="mt-4 font-mono text-[10px] leading-relaxed text-zinc-600">
                  {scene.bundle_id}
                </p>
              </div>
            }
          />
        </div>
      ) : (
        <div className="mt-16 max-w-md">
          <p className="text-xl font-normal leading-relaxed text-zinc-200">
            {meta.description}
          </p>
          {scene.status === "failed_incomplete" && scene.missing_paths && (
            <p className="mt-4 text-sm text-zinc-500">
              {scene.missing_paths.length} capture file
              {scene.missing_paths.length === 1 ? "" : "s"} still missing.
            </p>
          )}
          {!meta.terminal && (
            <p className="mt-8 text-xs text-zinc-600">
              This page updates when the room is ready.
            </p>
          )}
          <p className="mt-10 border-t border-white/[0.06] pt-6 font-mono text-[10px] text-zinc-600">
            {scene.bundle_id}
          </p>
        </div>
      )}
    </div>
  );
}

export default function RoomPage() {
  return (
    <div className="mx-auto max-w-6xl px-6 py-14">
      <Suspense
        fallback={
          <div className="h-48 animate-pulse rounded-2xl border border-white/[0.06] bg-white/[0.02]" />
        }
      >
        <RoomDetail />
      </Suspense>
    </div>
  );
}
