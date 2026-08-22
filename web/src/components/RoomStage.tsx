"use client";

/**
 * The immersive stage for a ready room (design §4/§5): fetches the
 * scene's assets, holds at the threshold until invited (the reveal
 * never auto-plays; the hold survives per-browser via lib/seen), plays
 * the reveal — the room's measured boundary drawing itself, its surfaces
 * materializing in place, then the pieces settling, the leading few named
 * aloud (decision 0097) — and then settles into stage 1: the room
 * full-bleed, one guest line grounded in real counts, the live
 * conversation surface where the composer sits — falling back to the
 * disabled composer only when the conversation GET fails — and the
 * ledger-style inventory floating at the edge.
 *
 * Mount with key={sceneId} so a different room resets the choreography.
 * All three.js stays behind SplatViewer's PositionedSplat contract.
 */

import { AnimatePresence, motion } from "motion/react";
import { useCallback, useEffect, useMemo, useState } from "react";

import CallingCardSheet, {
  CallingCardButton,
} from "@/components/CallingCardSheet";
import Conversation from "@/components/conversation/Conversation";
import SplatViewer from "@/components/SplatViewer";
import { PillButton, SPRING } from "@/components/ui/spring";
import { DisabledComposer, Eyebrow, GuestLine } from "@/components/ui/voice";
import { getApiClient } from "@/lib/api";
import { ApiError, SceneNotReadyError } from "@/lib/api/client";
import {
  assembleScene,
  type DesignSpecDoc,
  type FusedObject,
  type PositionedSplat,
  type SceneManifest,
  type ShellDoc,
  type ShellPlane,
} from "@/lib/api/types";
import {
  applyDesignSpec,
  arrangementNote,
  orphanNote,
  type ProposedScene,
} from "@/lib/designSpec";
import { hasSeenReveal, markRevealSeen } from "@/lib/seen";
import { statusMeta } from "@/lib/status";
import {
  arrivalLine,
  countsLine,
  settledLine,
  settledQuietLine,
} from "@/lib/voice";

type AssetsResult =
  | { forScene: string; phase: "not_ready"; message: string }
  | { forScene: string; phase: "error"; message: string }
  | {
      forScene: string;
      phase: "ready";
      splats: PositionedSplat[];
      shell: ShellPlane[] | null;
      unrenderable: FusedObject[];
      manifest: SceneManifest;
      /** The shell VERBATIM, beside the renderer's planes. The card draws
       * measured geometry, and `assembleScene` deliberately keeps only what
       * renders — `measured_polygon` and the openings' frame do not survive
       * it (lib/card/measure.ts explains why both matter). */
      shellDoc: ShellDoc | null;
    };

// Shell grace window (0066): the shell task lands a beat after `ready`,
// so an ABSENT shell (field null — distinct from a written "unavailable"
// document, which settles immediately) earns a couple of quiet refetches
// before the room proceeds with the grid. Placeholder pacing — tune at
// the real-browser reveal watch CLAUDE.md already schedules.
const SHELL_GRACE_ATTEMPTS = 3; // total fetches, first included
const SHELL_GRACE_DELAY_MS = 4000;

type RevealPhase = "hold" | "assembling" | "settled";

export default function RoomStage({
  sceneId,
  status,
  createdAt,
}: {
  sceneId: string;
  status: string;
  createdAt: string;
}) {
  const [result, setResult] = useState<AssetsResult | null>(null);
  // Reading localStorage in the initializer is safe here: this component
  // only ever mounts client-side, after the scene fetch resolves.
  const [phase, setPhase] = useState<RevealPhase>(() =>
    hasSeenReveal(sceneId) ? "settled" : "hold",
  );
  const [freshReveal, setFreshReveal] = useState(false);
  const [cardOpen, setCardOpen] = useState(false);
  const [arrival, setArrival] = useState<string | null>(null);
  // Conversation is an enhancement layer: if its GET fails, the settled
  // layout degrades to the non-conversational shape (decision 0058).
  const [convDown, setConvDown] = useState(false);
  const onConvUnavailable = useCallback(() => setConvDown(true), []);

  const assets = useMemo(
    () =>
      result && result.forScene === sceneId
        ? result
        : { phase: "loading" as const },
    [result, sceneId],
  );

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        let sceneAssets = await getApiClient().getSceneAssets(sceneId);
        // Absent shell (null/undefined) may just be a beat behind ready —
        // refetch briefly. A present doc (ready OR unavailable) settles
        // immediately; exhausted retries proceed with the grid.
        for (
          let attempt = 1;
          sceneAssets.shell == null && attempt < SHELL_GRACE_ATTEMPTS;
          attempt++
        ) {
          await new Promise((r) => setTimeout(r, SHELL_GRACE_DELAY_MS));
          if (cancelled) return;
          sceneAssets = await getApiClient().getSceneAssets(sceneId);
        }
        if (cancelled) return;
        const { splats, shell, unrenderable } = assembleScene(sceneAssets);
        setResult({
          forScene: sceneId, phase: "ready", splats, shell, unrenderable,
          manifest: sceneAssets.manifest,
          shellDoc: sceneAssets.shell ?? null,
        });
      } catch (exc: unknown) {
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
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [sceneId]);

  // --- The proposed arrangement (decision 0131). The spec is a SIBLING
  // document, so it is fetched separately and overlaid; a room nobody has
  // rearranged pays for exactly one extra GET and renders identically.
  const [spec, setSpec] = useState<DesignSpecDoc | null>(null);
  const refreshSpec = useCallback(() => {
    getApiClient()
      .getDesignSpec(sceneId)
      .then(setSpec)
      // An unavailable spec degrades to the measured room, which is the
      // honest fallback and the only one that cannot mislead.
      .catch(() => setSpec(null));
  }, [sceneId]);
  // No reset here on purpose: the room page mounts this with key={scene_id}
  // (see the docstring), so a different room is a different instance and
  // there is no stale spec to clear. Clearing it here would also be a
  // synchronous setState in an effect body — the cascading-render class this
  // codebase has now fixed three times (NewRoomSheet, AccountMenu).
  useEffect(refreshSpec, [refreshSpec]);

  // Memoized because the overlay's output is SplatViewer's `splats` prop:
  // a fresh array every render would be harmless for the renderer (its key
  // is structural — decision 0133) but would re-run the placement effect on
  // every parent render for nothing.
  const proposed: ProposedScene = useMemo(
    () =>
      assets.phase === "ready"
        ? applyDesignSpec(assets.splats, assets.manifest, spec)
        : { splats: [], states: [], outlines: [], applied: [], orphaned: [] },
    [assets, spec],
  );

  const revertAll = useCallback(async () => {
    try {
      await getApiClient().clearDesignSpec(sceneId);
    } finally {
      refreshSpec();
    }
  }, [sceneId, refreshSpec]);

  const placed = assets.phase === "ready" ? assets.splats.length : 0;
  const seen = assets.phase === "ready" ? assets.unrenderable.length : 0;
  const hasShell = assets.phase === "ready" && (assets.shell?.length ?? 0) > 0;
  const changed = arrangementNote(proposed.applied);
  const orphans = orphanNote(proposed.orphaned);
  // This control clears the whole document, corrections included, so it is
  // labelled for what it actually does. "Back to measured" is exact while
  // every entry departs from a measurement; once a facing correction is in
  // the room it is not, because the facing the scan drew was never measured
  // (decision 0157) — and a room with ONLY corrections has nothing to put
  // back at all, so it gets no control.
  const corrections = proposed.applied.filter((e) => e.facing_flipped).length;
  const rearranged = proposed.applied.filter(
    (e) => e.departs_from === "measurement",
  ).length;

  const comeIn = () => {
    setFreshReveal(true);
    if (
      assets.phase === "ready" &&
      assets.splats.length === 0 &&
      (assets.shell?.length ?? 0) === 0
    ) {
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
          splats={proposed.splats}
          shell={assets.shell}
          outlines={proposed.outlines}
          frameless
          reveal={phase === "assembling"}
          onRevealStep={(_, label) => setArrival(label)}
          onRevealCaptionsDone={() => setArrival(null)}
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

      {/* Stage 1, settled: the conversation (card + live composer), or the
          non-conversational layout when the conversation layer is down. */}
      {phase === "settled" && (
        <>
          {/* The card a person can take away (social-layer.md §6). Quiet
              and under the chrome: the room is still the hero. */}
          <div className="absolute right-6 top-16 z-20">
            <CallingCardButton onClick={() => setCardOpen(true)} />
          </div>
          <div className="pointer-events-none absolute inset-x-0 bottom-0 flex justify-center px-6 pb-7">
            <div className="pointer-events-auto w-full max-w-2xl">
              {/* What this room is showing that the scan did not (0131).
                  Chrome, not the guest's voice: a plain statement about what
                  is on screen, with the way back always one control away —
                  0133 makes "back to measured" an invariant, not a feature. */}
              {changed && (
                <div className="mb-2.5 flex items-center justify-between gap-4 rounded-[12px] border border-ink/15 bg-paper/[0.96] px-4 py-2.5 shadow-float">
                  <p className="text-[12px] leading-snug text-ink/70">{changed}</p>
                  {rearranged > 0 && (
                    <button
                      onClick={revertAll}
                      className="shrink-0 rounded-full border border-ink/20 px-3 py-1 text-[11px] text-ink/70 transition-colors hover:bg-ink/[0.06]"
                    >
                      {corrections ? "back to the scan" : "back to measured"}
                    </button>
                  )}
                </div>
              )}
              {orphans && (
                <div className="mb-2.5 rounded-[12px] border border-ink/15 bg-paper/[0.96] px-4 py-2.5 shadow-float">
                  <p className="text-[12px] leading-snug text-ink/60">{orphans}</p>
                </div>
              )}
              {assets.phase === "ready" && !convDown ? (
                <Conversation
                  sceneId={sceneId}
                  greeting={
                    freshReveal ? arrivalLine(placed, hasShell) : settledLine(placed)
                  }
                  countsNote={countsLine(placed, seen)}
                  onUnavailable={onConvUnavailable}
                  onArrangementChanged={refreshSpec}
                />
              ) : (
                <>
                  <div className="rounded-[14px] border border-ink/15 bg-paper/[0.96] px-5 py-4 shadow-deep">
                    <GuestLine className="text-[15px]">
                      {freshReveal
                        ? arrivalLine(placed, hasShell)
                        : settledQuietLine(placed)}
                    </GuestLine>
                    {assets.phase === "ready" && (
                      <p className="mt-2 text-[11.5px] text-ink/55">
                        {countsLine(placed, seen)}
                      </p>
                    )}
                  </div>
                  <DisabledComposer className="mx-auto mt-3 max-w-xl" />
                </>
              )}
            </div>
          </div>

          {assets.phase === "ready" && placed + seen > 0 && (
            <div className="pointer-events-auto absolute bottom-7 left-6 hidden w-60 rounded-xl bg-paper/95 p-4 shadow-float lg:block">
              <Eyebrow>In this room — {placed + seen}</Eyebrow>
              <ul className="mt-2.5 max-h-[34vh] space-y-1.5 overflow-y-auto">
                {proposed.splats.map((s, i) => {
                  // State reads as words, not a badge (0057 deleted
                  // StatusBadge): "placed" is the measurement, "moved" and
                  // "taken out" are the proposal, and the difference between
                  // them is the point. "turned" is neither — the piece stands
                  // exactly where it was measured and the person told us which
                  // way it faces (0157), so it reads as a fact about the room
                  // rather than as something pending.
                  const state = proposed.states[i] ?? "measured";
                  return (
                    <li
                      key={`${s.label}-${i}`}
                      className="flex items-baseline justify-between gap-3 text-[13px]"
                    >
                      <span
                        className={
                          state === "removed"
                            ? "capitalize text-ink/40 line-through"
                            : "capitalize text-ink/85"
                        }
                      >
                        {s.label}
                      </span>
                      <span className="text-[10.5px] text-ink/40">
                        {state === "removed"
                          ? "taken out"
                          : state === "moved"
                            ? "moved"
                            : state === "turned"
                              ? "turned round"
                              : "placed"}
                      </span>
                    </li>
                  );
                })}
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

      <CallingCardSheet
        open={cardOpen}
        onClose={() => setCardOpen(false)}
        status={status}
        createdAt={createdAt}
        shell={assets.phase === "ready" ? assets.shellDoc : null}
        manifest={assets.phase === "ready" ? assets.manifest : null}
      />

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
