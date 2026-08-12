"use client";

/**
 * Developer splat viewer. The product path embeds the viewer in the room
 * page (RoomViewerPanel); this page is the workbench — hidden from the nav
 * in live mode. Sources, all funneling into the same PositionedSplat list:
 *
 *   /viewer?scene=<scene_id> — the room page's embedded flow, standalone.
 *   /viewer?url=<splat url>  — render a single splat file at origin.
 *   /viewer?fixture=<dir>    — a staged assets response from
 *                              /dev-fixtures/<dir>/assets.json (real-scene
 *                              adjudication fixtures).
 *   drag & drop a .ply/.spz/.splat/.ksplat file — same, from disk.
 *
 * With no source it tries /dev-fixtures/manifest.json (the synthetic room
 * from tools/make_synthetic_splat.py) and falls back to instructions.
 */

import { useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";

import RoomViewerPanel from "@/components/RoomViewerPanel";
import SplatViewer, { type ViewerLabel } from "@/components/SplatViewer";
import {
  assembleScene,
  type FusedObject,
  type PositionedSplat,
  type SceneAssets,
  type ShellPlane,
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
      shell: ShellPlane[] | null;
      unrenderable: FusedObject[];
      labels: ViewerLabel[] | null;
    };

/** Dev-only sidecar carried by staged review fixtures: wall letters +
 * placed-object numbers, shared with the 2D key maps so the two surfaces
 * can never disagree. Absent on real API responses. */
type WalkLabelSidecar = {
  _walk_labels?: {
    walls?: ViewerLabel[];
    objects?: ViewerLabel[];
  };
};

function singleSplat(key: string, url: string, label: string): Result {
  return {
    key,
    phase: "ready",
    shell: null,
    unrenderable: [],
    labels: null,
    splats: [
      { url, label, position: [0, 0.5, 0], rotation_xyzw: [0, 0, 0, 1], scale: 1 },
    ],
  };
}

function DevViewerContent({
  directUrl,
  fixture,
  reveal,
  showLabels,
}: {
  directUrl: string | null;
  fixture: string | null;
  reveal: boolean;
  showLabels: boolean;
}) {
  const key = directUrl ?? (fixture ? `fixture:${fixture}` : "");
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
      // Staged fixture dir, else the local dev fixture manifest.
      try {
        const resp = await fetch(
          fixture
            ? `/dev-fixtures/${encodeURIComponent(fixture)}/assets.json`
            : "/dev-fixtures/manifest.json",
        );
        if (!resp.ok) throw new Error("no fixture");
        const assets = (await resp.json()) as SceneAssets & WalkLabelSidecar;
        if (cancelled) return;
        const { splats, shell, unrenderable } = assembleScene(assets);
        const sidecar = assets._walk_labels;
        const labels = sidecar
          ? [...(sidecar.walls ?? []), ...(sidecar.objects ?? [])]
          : null;
        setResult(
          splats.length || shell?.length
            ? { key, phase: "ready", splats, shell, unrenderable, labels }
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
  }, [key, directUrl, fixture]);

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
        <div className="mt-8 h-[62vh] animate-pulse rounded-xl border border-ink/10 bg-parchment/60" />
      )}

      {state.phase === "idle" && (
        <div className="mt-8 flex h-[62vh] flex-col items-center justify-center rounded-xl border border-dashed border-ink/30 bg-parchment/40 text-center">
          <p className="text-ink/85">Drop a splat file to view it</p>
          <p className="mt-2 max-w-sm text-sm leading-relaxed text-ink/55">
            .ply, .spz, .splat or .ksplat — or generate the synthetic room
            fixture with <code className="font-mono text-xs">tools/make_synthetic_splat.py</code>.
          </p>
        </div>
      )}

      {state.phase === "ready" && (
        <>
          <SplatViewer
            splats={state.splats}
            shell={state.shell}
            reveal={reveal}
            labels={showLabels ? state.labels : null}
            className="mt-8 h-[62vh]"
          />
          {state.unrenderable.length > 0 && (
            <p className="mt-3 text-sm text-ink/55">
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
  const fixture = params.get("fixture");
  // ?reveal=1 replays the §4 assembly over the loaded fixture — a real-speed
  // reveal watch on a real room (13-wall spike shell) rather than in the
  // throttled preview pane or the hand-authored !v3 mock.
  const reveal = params.get("reveal") === "1";
  // ?labels=1 renders the fixture's _walk_labels sidecar as in-scene badges
  // (wall letters + piece numbers), so a reviewer can name what they see.
  const showLabels = params.get("labels") === "1";

  return (
    <div>
      <div className="flex items-baseline justify-between">
        <h1 className="text-3xl font-semibold tracking-tight">Viewer</h1>
        <span className="font-mono text-[10px] text-ink/40">dev workbench</span>
      </div>
      {sceneId ? (
        <div className="mt-8">
          <RoomViewerPanel sceneId={sceneId} className="h-[62vh]" />
        </div>
      ) : (
        <DevViewerContent
          directUrl={directUrl}
          fixture={fixture}
          reveal={reveal}
          showLabels={showLabels}
        />
      )}
    </div>
  );
}

export default function ViewerPage() {
  return (
    <div className="mx-auto max-w-6xl px-6 py-14">
      <Suspense
        fallback={
          <div className="h-[62vh] animate-pulse rounded-xl bg-parchment/60" />
        }
      >
        <ViewerContent />
      </Suspense>
    </div>
  );
}
