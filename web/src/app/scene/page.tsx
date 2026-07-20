"use client";

/**
 * Scene detail: /scene?bundle=<bundle_id>. Query-param routing because the
 * static export cannot prerender unknown dynamic path segments; a single
 * exported page reads the id client-side (useSearchParams requires the
 * Suspense boundary below during prerender).
 */

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import StatusBadge from "@/components/StatusBadge";
import { getApiClient } from "@/lib/api";
import { ApiError } from "@/lib/api/client";
import type { SceneSummary } from "@/lib/api/types";
import { statusMeta } from "@/lib/status";

/** Async-only result stamped with the bundle it was fetched for; a stale
 * stamp renders as loading ("missing" is derived from the URL directly),
 * so the effect never sets state synchronously. */
type Result =
  | { forBundle: string; phase: "error"; message: string }
  | { forBundle: string; phase: "ready"; scene: SceneSummary };

function SceneDetail() {
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
    getApiClient()
      .getSceneByBundle(bundleId)
      .then(
        (scene) =>
          !cancelled && setResult({ forBundle: bundleId, phase: "ready", scene }),
      )
      .catch((exc: unknown) => {
        if (cancelled) return;
        const message =
          exc instanceof ApiError ? exc.message : "Could not reach the server.";
        setResult({ forBundle: bundleId, phase: "error", message });
      });
    return () => {
      cancelled = true;
    };
  }, [bundleId]);

  if (state.phase === "missing") {
    return (
      <p className="text-zinc-400">
        No scene selected.{" "}
        <Link href="/scenes" className="text-sky-400 hover:underline">
          Back to your scenes
        </Link>
      </p>
    );
  }
  if (state.phase === "loading") {
    return <div className="h-40 animate-pulse rounded-xl border border-zinc-800 bg-zinc-900/40" />;
  }
  if (state.phase === "error") {
    return (
      <div className="rounded-xl border border-red-500/20 bg-red-500/5 p-6">
        <p className="text-sm font-medium text-red-300">Couldn&apos;t load this scene</p>
        <p className="mt-1 text-sm text-zinc-400">{state.message}</p>
      </div>
    );
  }

  const { scene } = state;
  const meta = statusMeta(scene.status);
  return (
    <div>
      <Link href="/scenes" className="text-sm text-zinc-500 hover:text-zinc-300">
        ← Your scenes
      </Link>
      <div className="mt-4 rounded-xl border border-zinc-800 bg-zinc-900/50 p-6">
        <div className="flex items-center justify-between gap-4">
          <h1 className="truncate font-mono text-sm text-zinc-400">{scene.bundle_id}</h1>
          <StatusBadge status={scene.status} />
        </div>
        <p className="mt-4 text-zinc-300">{meta.description}</p>
        {scene.status === "failed_incomplete" && scene.missing_paths && (
          <p className="mt-2 text-sm text-zinc-500">
            {scene.missing_paths.length} file
            {scene.missing_paths.length === 1 ? "" : "s"} missing from the upload.
          </p>
        )}
        <dl className="mt-6 grid grid-cols-2 gap-4 text-sm">
          <div>
            <dt className="text-zinc-500">Captured</dt>
            <dd className="mt-0.5 text-zinc-300">
              {new Date(scene.created_at).toLocaleString()}
            </dd>
          </div>
          <div>
            <dt className="text-zinc-500">Last update</dt>
            <dd className="mt-0.5 text-zinc-300">
              {new Date(scene.updated_at).toLocaleString()}
            </dd>
          </div>
        </dl>
        {scene.status === "ready" && (
          <Link
            href={`/viewer?scene=${scene.scene_id}`}
            className="mt-8 inline-block rounded-lg bg-sky-500 px-5 py-2.5 text-sm font-medium text-white transition hover:bg-sky-400"
          >
            Open your room
          </Link>
        )}
      </div>
    </div>
  );
}

export default function ScenePage() {
  return (
    <Suspense fallback={<div className="h-40 animate-pulse rounded-xl bg-zinc-900/40" />}>
      <SceneDetail />
    </Suspense>
  );
}
