/**
 * Status indicator: a colored dot + quiet sans label — how state reads in
 * restrained UI (decision 0056). The dot carries the tone; the text stays
 * neutral. In-flight states pulse.
 */

import type { SceneStatus } from "@/lib/api/types";
import { statusMeta, type StatusTone } from "@/lib/status";

const DOT_CLASSES: Record<StatusTone, string> = {
  progress: "bg-zinc-400",
  success: "bg-emerald-400",
  warning: "bg-orange-400",
  error: "bg-red-400",
};

export default function StatusBadge({ status }: { status: SceneStatus }) {
  const meta = statusMeta(status);
  return (
    <span className="inline-flex items-center gap-2 text-xs font-medium text-zinc-400">
      <span
        className={`h-1.5 w-1.5 rounded-full ${DOT_CLASSES[meta.tone]} ${
          meta.terminal ? "" : "animate-pulse"
        }`}
      />
      {meta.label}
    </span>
  );
}
