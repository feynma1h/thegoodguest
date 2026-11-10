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
import type { FurnitureBundle } from "@/lib/furniture";
import type { ShellFinish } from "@/lib/shellFinish";
import { loadShellExtras } from "@/lib/shellExtras";
import { PillButton, SPRING } from "@/components/ui/spring";
import { GuestLine } from "@/components/ui/voice";
import { Mark } from "@/components/Wordmark";
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
      /** The optional designed finish and furniture twins (decision 0313):
       * null unless the finish switch is on and the scene has files that fit;
       * with twins, `splats` and `unrenderable` above are empty. */
      finish: ShellFinish | null;
      furniture: FurnitureBundle | null;
    };

// Shell grace window (0066): the shell task lands a beat after `ready`,
// so an ABSENT shell (field null — distinct from a written "unavailable"
// document, which settles immediately) earns a couple of quiet refetches
// before the room proceeds with the grid. Placeholder pacing — tune at
// the real-browser reveal watch PROJECT.md already schedules.
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
        // The finish and twins are read before the room is drawn, so a room
        // with twins never shows its scanned objects first and then swaps
        // (decision 0341). Never throws, is bounded by EXTRAS_TIMEOUT_MS, and
        // with no finish files makes no request and comes back empty.
        const extras = await loadShellExtras(
          sceneAssets,
          (shell ?? []).filter((p) => p.kind === "wall").length,
        );
        if (cancelled) return;
        // Twins ARE the room's objects: when they are drawn, the scan's own
        // objects (splats, the list of them) are not part of it.
        const twins = extras.furniture !== null;
        setResult({
          forScene: sceneId, phase: "ready",
          splats: twins ? [] : splats, shell,
          unrenderable: twins ? [] : unrenderable,
          manifest: sceneAssets.manifest,
          shellDoc: sceneAssets.shell ?? null,
          ...extras,
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
        ? // A rearranged-room proposal moves scanned objects; a room of twins has none.
          applyDesignSpec(assets.splats, assets.manifest, assets.furniture ? null : spec)
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

  // The guest's words and counts are about the pieces on screen: the twins
  // when the room is drawn from them, else the scan's placed objects.
  const scanned = assets.phase === "ready" ? assets.splats.length : 0;
  const placed =
    assets.phase === "ready" && assets.furniture ? assets.furniture.objects.length : scanned;
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
      {/* The room itself, left of the conversation rail on wide screens
          (decision 0361). The finish rig puts its view control at the foot
          of this region, where nothing sits on top of it. */}
      <div className="absolute inset-0 lg:right-[460px]">
        {assets.phase === "ready" && phase !== "hold" && (
          <SplatViewer
            splats={proposed.splats}
            shell={assets.shell}
            finish={assets.finish}
            furniture={assets.furniture}
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
            <p className="max-w-sm text-center text-sm leading-relaxed text-on-dusk-2">
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
                className="rounded-full bg-dusk-3 px-4 py-1.5 shadow-float"
              >
                <GuestLine tone="cream" className="text-[14px]">the {arrival}</GuestLine>
              </motion.div>
            )}
          </AnimatePresence>
        </div>

        {phase === "settled" && (
          /* The card a person can take away (social-layer.md §6). Quiet and
             under the chrome: the room is still the hero. */
          <div className="absolute right-5 top-[72px] z-20 sm:right-7">
            <CallingCardButton onClick={() => setCardOpen(true)} />
          </div>
        )}
      </div>

      {/* Stage 1, settled: the conversation rail (or the non-conversational
          layout when the conversation layer is down), and the inventory. */}
      {phase === "settled" && (
        <>
          <aside
            aria-label="Conversation with the guest"
            className="absolute inset-x-3 bottom-3 z-20 flex max-h-[48%] flex-col overflow-hidden rounded-3xl border border-on-dusk/[0.08] bg-dusk-2 lg:inset-x-auto lg:bottom-4 lg:right-4 lg:top-4 lg:max-h-none lg:w-[428px]"
          >
            <div className="flex items-center justify-between gap-3 px-6 pb-3 pt-5">
              <div className="flex items-center gap-2.5">
                <Mark height="13px" />
                <h2 className="text-[15px] font-semibold text-on-dusk">The guest</h2>
              </div>
              <span className="text-[13px] text-on-dusk-2">Answers from what it measured</span>
            </div>
            {/* What this room is showing that the scan did not (0131).
                Chrome, not the guest's voice: a plain statement about what is
                on screen, with the way back always one control away — 0133
                makes "back to measured" an invariant, not a feature. */}
            {(changed || orphans) && (
              <div className="space-y-2 px-4 pb-2">
                {changed && (
                  <div className="flex items-center justify-between gap-4 rounded-[14px] bg-dusk-3 px-4 py-2.5">
                    <p className="text-[13px] leading-snug text-on-dusk">{changed}</p>
                    {rearranged > 0 && (
                      <button
                        onClick={revertAll}
                        className="shrink-0 cursor-pointer rounded-full px-3 py-1.5 text-[12.5px] font-medium text-on-dusk ring-1 ring-inset ring-on-dusk/25 transition-colors hover:bg-dusk"
                      >
                        {corrections ? "Back to the scan" : "Back to measured"}
                      </button>
                    )}
                  </div>
                )}
                {orphans && (
                  <div className="rounded-[14px] bg-dusk-3 px-4 py-2.5">
                    <p className="text-[13px] leading-snug text-on-dusk-2">{orphans}</p>
                  </div>
                )}
              </div>
            )}
            <div className="min-h-0 flex-1">
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
                <div className="flex h-full flex-col justify-end gap-2 px-6 pb-6">
                  <GuestLine tone="cream" className="text-[19px] leading-[1.45]">
                    {freshReveal
                      ? arrivalLine(placed, hasShell)
                      : settledQuietLine(placed)}
                  </GuestLine>
                  {assets.phase === "ready" && (
                    <p className="text-[13.5px] text-on-dusk-2">
                      {countsLine(placed, seen)}
                    </p>
                  )}
                </div>
              )}
            </div>
          </aside>

          {assets.phase === "ready" && scanned + seen > 0 && (
            <section
              aria-labelledby="inventory-heading"
              className="pointer-events-auto absolute bottom-5 left-5 z-10 hidden w-[288px] rounded-[20px] border border-on-dusk/[0.08] bg-dusk-2 px-5 pb-3 pt-[18px] lg:block"
            >
              <div className="mb-2 flex items-baseline justify-between">
                <h2 id="inventory-heading" className="text-[15px] font-semibold text-on-dusk">
                  In this room
                </h2>
                <span className="text-[13px] text-on-dusk-2">
                  {scanned + seen} {scanned + seen === 1 ? "piece" : "pieces"}
                </span>
              </div>
              <ul className="max-h-[34vh] overflow-y-auto">
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
                      className="flex items-baseline justify-between gap-3 border-t border-on-dusk/[0.07] py-[9px] text-[14.5px]"
                    >
                      <span
                        className={
                          state === "removed"
                            ? "capitalize text-on-dusk-2 line-through"
                            : "capitalize text-on-dusk"
                        }
                      >
                        {s.label}
                      </span>
                      <span className={`text-[13px] ${state === "measured" ? "text-on-dusk-2" : "text-sun"}`}>
                        {state === "removed"
                          ? "Taken out"
                          : state === "moved"
                            ? "Moved"
                            : state === "turned"
                              ? "Turned round"
                              : "Placed"}
                      </span>
                    </li>
                  );
                })}
                {assets.unrenderable.map((o) => (
                  <li
                    key={o.object_id}
                    className="flex items-baseline justify-between gap-3 border-t border-on-dusk/[0.07] py-[9px] text-[14.5px]"
                    title={`Seen but not yet placed (${o.reason ?? "no transform"})`}
                  >
                    <span className="capitalize text-on-dusk-2">{o.label}</span>
                    <span className="text-[13px] text-on-dusk-2">Seen, not placed</span>
                  </li>
                ))}
              </ul>
            </section>
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
