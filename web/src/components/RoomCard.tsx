"use client";

/**
 * One room in the /rooms grid. Links to the room page by bundle_id
 * (query-param routing — static export cannot prerender unknown dynamic
 * segments). Rooms have no user-given names yet, so the card leads with
 * the capture moment; the bundle id stays as quiet mono metadata
 * (machine data — the one legitimate mono use here).
 */

import type { SceneSummary } from "@/lib/api/types";
import { MotionLink, SPRING } from "@/components/ui/spring";
import StatusBadge from "./StatusBadge";

function formatWhen(iso: string): { day: string; time: string } {
  const d = new Date(iso);
  return {
    day: d.toLocaleDateString(undefined, { month: "long", day: "numeric" }),
    time: d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" }),
  };
}

export default function RoomCard({ scene }: { scene: SceneSummary }) {
  const when = formatWhen(scene.created_at);
  const ready = scene.status === "ready";
  return (
    <MotionLink
      href={`/room?bundle=${scene.bundle_id}`}
      whileHover={{ y: -2 }}
      whileTap={{ scale: 0.99 }}
      transition={SPRING}
      className="group block rounded-2xl border border-white/[0.06] bg-white/[0.02] p-6 transition-colors hover:border-white/[0.14] hover:bg-white/[0.04]"
    >
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold tracking-tight text-foreground">
            Room · {when.day}
          </h2>
          <p className="mt-1 text-sm text-zinc-500">Captured at {when.time}</p>
        </div>
        <StatusBadge status={scene.status} />
      </div>
      <div className="mt-8 flex items-end justify-between">
        <span className="truncate font-mono text-[10px] text-zinc-600">
          {scene.bundle_id}
        </span>
        <span className="text-sm text-zinc-500 transition-colors group-hover:text-foreground">
          {ready ? "Step inside →" : "Details →"}
        </span>
      </div>
    </MotionLink>
  );
}
