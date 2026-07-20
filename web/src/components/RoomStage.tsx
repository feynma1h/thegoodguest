"use client";

/**
 * The immersive stage for a ready room (design §4/§5): fetches the
 * scene's assets, holds at the threshold until invited (the reveal
 * never auto-plays; the hold survives per-browser via lib/seen), plays
 * the objects-first assembly — each piece named as it lands — and then
 * settles into stage 1: the room full-bleed, one guest line grounded in
 * real counts, the disabled composer holding the conversation's place,
 * and the ledger-style inventory floating at the edge.
 *
 * Mount with key={sceneId} so a different room resets the choreography.
 * All three.js stays behind SplatViewer's PositionedSplat contract.
 */

import { AnimatePresence, motion } from "motion/react";
import { useEffect, useState } from "react";

import SplatViewer from "@/components/SplatViewer";
import { PillButton, SPRING } from "@/components/ui/spring";
import { DisabledComposer, Eyebrow, GuestLine } from "@/components/ui/voice";
import { getApiClient } from "@/lib/api";
import { ApiError, SceneNotReadyError } from "@/lib/api/client";
import {
  assembleScene,
  type FusedObject,
  type PositionedSplat,
} from "@/lib/api/types";
import { hasSeenReveal, markRevealSeen } from "@/lib/seen";
import { statusMeta } from "@/lib/status";
import { arrivalLine, countsLine, settledLine } from "@/lib/voice";

type AssetsResult =
  | { forScene: string; phase: "not_ready"; message: string }
  | { forScene: string; phase: "error"; message: string }
  | {
      forScene: string;
      phase: "ready";
      splats: PositionedSplat[];
      unrenderable: FusedObject[];
    };

type RevealPhase = "hold" | "assembling" | "settled";

export default function RoomStage({ sceneId }: { sceneId: string }) {
  const [result, setResult] = useState<AssetsResult | null>(null);
  // Reading localStorage in the initializer is safe here: this component
  // only ever mounts client-side, after the scene fetch resolves.
  const [phase, setPhase] = useState<RevealPhase>(() =>
    hasSeenReveal(sceneId) ? "settled" : "hold",
  );
  const [freshReveal, setFreshReveal] = useState(false);
  const [arrival, setArrival] = useState<string | null>(null);

  const assets =
    result && result.forScene === sceneId ? result : { phase: "loading" as const };

  useEffect(() => {
    let cancelled = false;
    getApiClient()
      .getSceneAssets(sceneId)
      .then((sceneAssets) => {
        if (cancelled) return;
        const { splats, unrenderable } = assembleScene(sceneAssets);
        setResult({ forScene: sceneId, phase: "ready", splats, unrenderable });
      })
      .catch((exc: unknown) => {
        if (cancelled) return;
        if (exc instanceof SceneNotReadyError) {
          setResult({
            forScene: sceneId,
            phase: "not_ready",
            message: statusMeta(exc.sceneStatus).description,
          });
        } else {
          setResult({
            forScene: sceneId,
            phase: "error",
            message:
              exc instanceof ApiError ? exc.message : "Could not load this room.",
          });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [sceneId]);

  const placed = assets.phase === "ready" ? assets.splats.length : 0;
  const seen = assets.phase === "ready" ? assets.unrenderable.length : 0;

  const comeIn = () => {
    setFreshReveal(true);
    if (assets.phase === "ready" && assets.splats.length === 0) {
      // Nothing to assemble — settle straight into the honest empty room.
      markRevealSeen(sceneId);
      setPhase("settled");
    } else {
      setPhase("assembling");
    }
  };

  const onRevealDone = () => {
    markRevealSeen(sceneId);
    setArrival(null);
    setPhase("settled");
  };

  return (
    <div className="absolute inset-0">
      {/* The room itself. */}
      {assets.phase === "ready" && phase !== "hold" && (
        <SplatViewer
          splats={assets.splats}
          frameless
          reveal={phase === "assembling"}
          onRevealStep={(_, label) => setArrival(label)}
          onRevealDone={onRevealDone}
          className="h-full"
        />
      )}

      {/* Stage-level notices (assets still loading / unavailable). */}
      {phase !== "hold" && assets.phase !== "ready" && (
        <div className="flex h-full items-center justify-center px-6">
          <p className="max-w-sm text-center text-sm leading-relaxed text-paper/60">
            {assets.phase === "loading"
              ? "Opening the door…"
              : assets.message}
          </p>
        </div>
      )}

      {/* Naming each piece as it lands (§4's assembly captions). */}
      <div className="pointer-events-none absolute inset-x-0 bottom-24 flex justify-center">
        <AnimatePresence mode="wait">
          {phase === "assembling" && arrival && (
            <motion.div
              key={arrival}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              transition={SPRING}
              className="rounded-full bg-paper/95 px-4 py-1.5 shadow-float"
            >
              <GuestLine className="text-[13.5px]">the {arrival}</GuestLine>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* Stage 1, settled: one guest line, the composer's place, the ledger. */}
      {phase === "settled" && (
        <>
          <div className="pointer-events-none absolute inset-x-0 bottom-0 flex justify-center px-6 pb-7">
            <div className="pointer-events-auto w-full max-w-2xl">
              <div className="rounded-[14px] border border-ink/15 bg-paper/[0.96] px-5 py-4 shadow-deep">
                <GuestLine className="text-[15px]">
                  {freshReveal ? arrivalLine(placed) : settledLine(placed)}
                </GuestLine>
                {assets.phase === "ready" && (
                  <p className="mt-2 text-[11.5px] text-ink/55">
                    {countsLine(placed, seen)}
                  </p>
                )}
              </div>
              <DisabledComposer className="mx-auto mt-3 max-w-xl" />
            </div>
          </div>

          {assets.phase === "ready" && placed + seen > 0 && (
            <div className="pointer-events-auto absolute bottom-7 left-6 hidden w-60 rounded-xl bg-paper/95 p-4 shadow-float lg:block">
              <Eyebrow>In this room — {placed + seen}</Eyebrow>
              <ul className="mt-2.5 max-h-[34vh] space-y-1.5 overflow-y-auto">
                {assets.splats.map((s, i) => (
                  <li
                    key={`${s.label}-${i}`}
                    className="flex items-baseline justify-between gap-3 text-[13px]"
                  >
                    <span className="capitalize text-ink/85">{s.label}</span>
                    <span className="text-[10.5px] text-ink/40">placed</span>
                  </li>
                ))}
                {assets.unrenderable.map((o) => (
                  <li
                    key={o.object_id}
                    className="flex items-baseline justify-between gap-3 text-[13px]"
                    title={`Seen but not yet placed (${o.reason ?? "no transform"})`}
                  >
                    <span className="capitalize text-ink/45">{o.label}</span>
                    <span className="text-[10.5px] text-ink/40">seen</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}

      {/* The threshold (§4): nothing auto-plays; the room waits. */}
      <AnimatePresence>
        {phase === "hold" && (
          <motion.div
            initial={false}
            exit={{ opacity: 0, transition: { duration: 0.5 } }}
            className="absolute inset-0 z-20 flex flex-col items-center justify-center bg-ink px-6 text-center"
          >
            <GuestLine tone="cream" className="max-w-md text-[19px]">
              It&rsquo;s ready. Come in when you have a minute — this is worth
              your full attention.
            </GuestLine>
            <PillButton variant="cream" onClick={comeIn} className="mt-9">
              come in
            </PillButton>
            <p className="mt-5 text-xs text-paper/45">
              in your own time — it holds still until you&rsquo;re ready
            </p>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
