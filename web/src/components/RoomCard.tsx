"use client";

/**
 * One room in the house (decision 0361) — a sibling, not a row (design §9).
 * The top of the card shows what the room IS right now, and the foot names
 * it in words:
 *
 *   ready        — its measured floor plan, the calling card's own drawing
 *                  (PlanFigure), so every number on it is a measurement
 *   in flight    — dusk and lamplight, with the guest's line for the wait
 *   partly here  — a dashed outline, and how many pieces never arrived
 *   failed       — what happened, in one line, and what to do
 *
 * The plan needs the room's shell, so a ready card fetches its assets once.
 * Links by bundle_id (query-param routing — the static export cannot
 * prerender unknown dynamic segments).
 */

import { useEffect, useState } from "react";

import PlanFigure from "@/components/PlanFigure";
import { MotionLink, SPRING } from "@/components/ui/spring";
import { getApiClient } from "@/lib/api";
import type { SceneSummary } from "@/lib/api/types";
import { measureRoom, type RoomMeasure } from "@/lib/card/measure";
import {
  agoPhrase,
  capitalize,
  minutesSince,
  missingPiecesLine,
  roomTitle,
  waitNarration,
} from "@/lib/voice";

function scannedOn(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { month: "long", day: "numeric" });
}

/** The ready room's plan: loading, drawn, or not drawable. */
export type Plan = { phase: "loading" } | { phase: "drawn"; measure: RoomMeasure } | { phase: "none" };

/** A ready room's measured plan, fetched once per room (its assets carry
 * the shell). Rooms that aren't ready — or no room — have no plan to fetch. */
export function useRoomPlan(scene: SceneSummary | null): Plan {
  const sceneId = scene?.status === "ready" ? scene.scene_id : null;
  const [plan, setPlan] = useState<{ forScene: string; plan: Plan } | null>(null);

  useEffect(() => {
    if (sceneId === null) return;
    let cancelled = false;
    getApiClient()
      .getSceneAssets(sceneId)
      .then((assets) => {
        if (cancelled) return;
        const measure = measureRoom(assets.shell, assets.manifest);
        setPlan({
          forScene: sceneId,
          plan: measure ? { phase: "drawn", measure } : { phase: "none" },
        });
      })
      .catch(() => {
        if (!cancelled) setPlan({ forScene: sceneId, plan: { phase: "none" } });
      });
    return () => {
      cancelled = true;
    };
  }, [sceneId]);

  if (sceneId === null) return { phase: "none" };
  return plan && plan.forScene === sceneId ? plan.plan : { phase: "loading" };
}

/** The top of a card, by what the room is right now. */
function CardFace({ scene, plan }: { scene: SceneSummary; plan: Plan }) {
  const title = roomTitle(scene.created_at);

  if (scene.status === "queued" || scene.status === "processing") {
    return (
      <div className="relative flex h-[250px] flex-col justify-end overflow-hidden bg-dusk p-6">
        <span
          aria-hidden
          className="breathe absolute left-1/2 top-[42%] h-[180px] w-[180px] -translate-x-1/2 -translate-y-1/2 rounded-full"
          style={{
            background:
              scene.status === "processing"
                ? "radial-gradient(circle, rgba(240,178,106,0.38) 0%, rgba(240,178,106,0) 70%)"
                : "radial-gradient(circle, rgba(240,178,106,0.22) 0%, rgba(240,178,106,0) 70%)",
          }}
        />
        <p className="relative font-serif text-[19px] italic leading-[1.35] text-on-dusk">
          {waitNarration(scene.status, minutesSince(scene.created_at))}
        </p>
      </div>
    );
  }

  if (scene.status === "failed_incomplete") {
    return (
      <div className="grid h-[250px] place-items-center bg-[#eef1f4]">
        <svg width="208" height="160" viewBox="0 0 208 160" aria-hidden>
          <path
            d="M2 2 H206 V158 H2 Z"
            fill="none"
            stroke="#808b98"
            strokeWidth="2.5"
            strokeDasharray="10 9"
          />
        </svg>
      </div>
    );
  }

  if (scene.status === "failed" || scene.status === "failed_invalid") {
    return (
      <div className="flex h-[250px] items-center justify-center bg-[#eef1f4] p-7">
        <p className="text-center font-serif text-[19px] italic leading-[1.4] text-ink-2">
          {scene.status === "failed_invalid"
            ? "This scan arrived in a form I can’t read."
            : "This scan didn’t survive the trip."}
        </p>
      </div>
    );
  }

  // Ready: the measured plan.
  return (
    <div className="relative h-[250px] bg-[#eef1f4]">
      {plan.phase === "drawn" ? (
        <PlanFigure
          measure={plan.measure}
          label={`The measured floor plan of ${title}`}
          className="absolute inset-0 h-full w-full p-3"
        />
      ) : plan.phase === "loading" ? (
        <div aria-hidden className="breathe absolute inset-10 rounded-lg bg-white/70" />
      ) : (
        <p className="absolute inset-0 grid place-items-center px-8 text-center text-[15px] text-ink-2">
          No floor plan to draw for this one.
        </p>
      )}
    </div>
  );
}

export default function RoomCard({ scene }: { scene: SceneSummary }) {
  const plan = useRoomPlan(scene);
  const inFlight = scene.status === "queued" || scene.status === "processing";
  const name = inFlight ? "A new room" : capitalize(roomTitle(scene.created_at));

  const meta =
    scene.status === "ready"
      ? `Scanned ${scannedOn(scene.created_at)}`
      : scene.status === "processing"
        ? `Being rebuilt. Arrived ${agoPhrase(scene.created_at)}.`
        : scene.status === "queued"
          ? `In line. Arrived ${agoPhrase(scene.created_at)}.`
          : scene.status === "failed_incomplete"
            ? missingPiecesLine(scene.missing_paths?.length ?? 0)
            : "Nothing to show. Scan it again from your phone.";

  return (
    <MotionLink
      href={`/room?bundle=${scene.bundle_id}`}
      whileHover={{ y: -2 }}
      whileTap={{ scale: 0.99 }}
      transition={SPRING}
      className="group block overflow-hidden rounded-3xl bg-white text-ink shadow-[0_1px_0_rgba(18,26,35,0.04),0_14px_34px_rgba(18,26,35,0.06)] transition-shadow hover:shadow-[0_1px_0_rgba(18,26,35,0.04),0_20px_44px_rgba(18,26,35,0.09)]"
    >
      <CardFace scene={scene} plan={plan} />
      <div className="flex items-end justify-between gap-3 px-[22px] pb-5 pt-[18px]">
        <div className="min-w-0">
          <h2 className="font-serif text-[22px] leading-[1.2]">{name}</h2>
          <p
            className={`mt-1.5 text-[14px] leading-[1.45] ${
              scene.status === "failed_incomplete" ? "text-accent-deep" : "text-ink-2"
            }`}
          >
            {meta}
          </p>
        </div>
        {scene.status === "ready" && (
          <span className="whitespace-nowrap text-[14px] font-semibold">Step inside</span>
        )}
      </div>
    </MotionLink>
  );
}
