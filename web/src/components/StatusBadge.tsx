/**
 * Status indicator: a colored dot + quiet sans label — state as a quiet
 * signal, kept from 0056 and re-palettized by 0057. Gold is the one
 * in-flight tone (light on its way — the sun/light charter); failures
 * read in rust. The dot carries the tone; the text stays neutral.
 * In-flight states pulse.
 */

import type { SceneStatus } from "@/lib/api/types";
import { statusMeta, type StatusTone } from "@/lib/status";

const DOT_CLASSES: Record<StatusTone, string> = {
  progress: "bg-sun",
  success: "bg-ink/40",
  warning: "bg-accent/60",
  error: "bg-accent",
};

export default function StatusBadge({ status }: { status: SceneStatus }) {
  const meta = statusMeta(status);
  return (
    <span className="inline-flex items-center gap-2 text-xs font-medium text-ink/60">
      <span
        className={`h-1.5 w-1.5 rounded-full ${DOT_CLASSES[meta.tone]} ${
          meta.terminal ? "" : "animate-pulse"
        }`}
      />
      {meta.label}
    </span>
  );
}
