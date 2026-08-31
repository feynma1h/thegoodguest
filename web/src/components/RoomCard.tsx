"use client";

/**
 * One room in the house grid — a sibling, not a row (design §9). The
 * card is a stage: a placeholder hatch where the room's likeness will
 * eventually render (no thumbnail pipeline yet), a cream bar carrying
 * the derived serif title and honest meta. State reads as treatment +
 * words, not badges: in-flight rooms dim the stage and narrate; failed
 * rooms say what happened in one line. Links by bundle_id (query-param
 * routing — static export cannot prerender unknown dynamic segments).
 */

import type { SceneSummary } from "@/lib/api/types";
import { MotionLink, SPRING } from "@/components/ui/spring";
import { statusMeta } from "@/lib/status";
import { elapsedPhrase, roomTitle } from "@/lib/voice";

function formatWhen(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, {
    month: "long",
    day: "numeric",
  });
}

export default function RoomCard({ scene }: { scene: SceneSummary }) {
  const meta = statusMeta(scene.status);
  const title = roomTitle(scene.created_at);
  const inFlight = scene.status === "queued" || scene.status === "processing";

  const failureLine =
    scene.status === "failed_incomplete"
      ? "part of the scan never arrived — finish it from your iPhone"
      : scene.status === "failed" || scene.status === "failed_invalid"
        ? "this scan didn't survive the trip"
        : null;

  return (
    <MotionLink
      href={`/room?bundle=${scene.bundle_id}`}
      whileHover={{ y: -2 }}
      whileTap={{ scale: 0.99 }}
      transition={SPRING}
      className="group relative block h-72 overflow-hidden rounded-xl border border-ink/20 bg-white transition-colors hover:border-ink/40"
    >
      {/* The stage — a quiet hatch until rooms have likenesses. */}
      <div className={`hatch absolute inset-0 ${inFlight ? "opacity-50" : ""}`} aria-hidden />

      {inFlight ? (
        <div className="absolute inset-x-0 top-[38%] px-6 text-center">
          <p className="text-xs font-medium text-ink/60">
            {title} — still being rebuilt
          </p>
          <p className="mt-1.5 text-[11.5px] text-ink/50">
            {/* One expression: this SWC version eats the space between an
                expression and following entity-bearing text. */}
            {`${elapsedPhrase(scene.created_at)} · it knocks when it’s ready`}
          </p>
        </div>
      ) : (
        <div className="absolute inset-x-0 bottom-0 bg-paper/[0.97] px-4 py-3.5">
          <div className="flex items-baseline justify-between gap-3">
            <h2 className="font-serif text-[15px] italic text-ink">{title}</h2>
            {scene.status === "ready" && (
              <span className="whitespace-nowrap text-xs text-ink/45 transition-colors group-hover:text-accent-deep">
                step inside →
              </span>
            )}
          </div>
          <p className="mt-1 text-[11.5px] leading-relaxed text-ink/55">
            {failureLine ? (
              <>
                <span
                  className={`mr-1.5 inline-block h-1.5 w-1.5 rounded-full align-middle ${
                    meta.tone === "warning" ? "bg-accent/60" : "bg-accent"
                  }`}
                />
                {failureLine}
              </>
            ) : (
              <>scanned {formatWhen(scene.created_at)}</>
            )}
          </p>
        </div>
      )}
    </MotionLink>
  );
}
