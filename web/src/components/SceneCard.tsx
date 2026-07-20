/**
 * One scene in the /scenes grid. Links to the detail page by bundle_id
 * (query-param routing — static export cannot prerender unknown dynamic
 * segments).
 */

import Link from "next/link";

import type { SceneSummary } from "@/lib/api/types";
import StatusBadge from "./StatusBadge";

function formatWhen(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export default function SceneCard({ scene }: { scene: SceneSummary }) {
  return (
    <Link
      href={`/scene?bundle=${scene.bundle_id}`}
      className="group block rounded-xl border border-zinc-800 bg-zinc-900/50 p-5 transition hover:border-zinc-600 hover:bg-zinc-900"
    >
      <div className="flex items-center justify-between gap-3">
        <span className="truncate font-mono text-xs text-zinc-500">
          {scene.bundle_id}
        </span>
        <StatusBadge status={scene.status} />
      </div>
      <div className="mt-4 flex items-baseline justify-between">
        <p className="text-sm text-zinc-300">Captured {formatWhen(scene.created_at)}</p>
        <span className="text-xs text-zinc-600 transition group-hover:text-zinc-400">
          View →
        </span>
      </div>
    </Link>
  );
}
