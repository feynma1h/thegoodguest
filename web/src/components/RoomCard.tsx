/**
 * One room in the /rooms grid. Links to the room page by bundle_id
 * (query-param routing — static export cannot prerender unknown dynamic
 * segments). Rooms have no user-given names yet, so the card leads with
 * the capture moment; the bundle id stays as quiet mono metadata.
 */

import Link from "next/link";

import type { SceneSummary } from "@/lib/api/types";
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
    <Link
      href={`/room?bundle=${scene.bundle_id}`}
      className="ease-soft group relative block overflow-hidden rounded-2xl border border-white/[0.06] bg-white/[0.02] p-6 transition-all duration-300 hover:-translate-y-0.5 hover:border-white/[0.14] hover:bg-white/[0.04]"
    >
      {/* Warm light seeps into ready rooms. */}
      {ready && (
        <div
          aria-hidden
          className="pointer-events-none absolute -right-16 -top-20 h-48 w-64 rounded-full bg-accent/10 blur-3xl transition-opacity duration-300 group-hover:bg-accent/15"
        />
      )}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="font-serif text-xl text-foreground">Room · {when.day}</h2>
          <p className="mt-1 text-sm text-zinc-500">Captured at {when.time}</p>
        </div>
        <StatusBadge status={scene.status} />
      </div>
      <div className="mt-8 flex items-end justify-between">
        <span className="truncate font-mono text-[10px] tracking-wider text-zinc-600">
          {scene.bundle_id}
        </span>
        <span className="ease-soft text-sm text-zinc-500 transition-all duration-300 group-hover:translate-x-0.5 group-hover:text-accent">
          {ready ? "Step inside →" : "Details →"}
        </span>
      </div>
    </Link>
  );
}
