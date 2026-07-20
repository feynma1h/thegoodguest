/**
 * Small status pill used on scene cards and the scene detail page.
 * Tone→color mapping is the app's single visual encoding of SceneStatus.
 */

import type { SceneStatus } from "@/lib/api/types";
import { statusMeta, type StatusTone } from "@/lib/status";

const TONE_CLASSES: Record<StatusTone, string> = {
  progress: "bg-sky-500/10 text-sky-300 ring-sky-500/30",
  success: "bg-emerald-500/10 text-emerald-300 ring-emerald-500/30",
  warning: "bg-amber-500/10 text-amber-300 ring-amber-500/30",
  error: "bg-red-500/10 text-red-300 ring-red-500/30",
};

export default function StatusBadge({ status }: { status: SceneStatus }) {
  const meta = statusMeta(status);
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset ${TONE_CLASSES[meta.tone]}`}
    >
      {!meta.terminal && (
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-current" />
      )}
      {meta.label}
    </span>
  );
}
