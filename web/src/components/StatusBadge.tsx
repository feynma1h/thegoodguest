/**
 * Small status pill used on scene cards and the scene detail page.
 * Tone→color mapping is the app's single visual encoding of SceneStatus.
 */

import type { SceneStatus } from "@/lib/api/types";
import { statusMeta, type StatusTone } from "@/lib/status";

const TONE_CLASSES: Record<StatusTone, string> = {
  progress: "bg-white/[0.04] text-zinc-300 ring-white/10",
  success: "bg-emerald-500/10 text-emerald-300 ring-emerald-500/25",
  warning: "bg-accent/10 text-accent ring-accent/25",
  error: "bg-red-500/10 text-red-300/90 ring-red-500/25",
};

export default function StatusBadge({ status }: { status: SceneStatus }) {
  const meta = statusMeta(status);
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 font-mono text-[10px] uppercase tracking-widest ring-1 ring-inset ${TONE_CLASSES[meta.tone]}`}
    >
      {!meta.terminal && (
        <span className="h-1 w-1 animate-pulse rounded-full bg-current" />
      )}
      {meta.label}
    </span>
  );
}
