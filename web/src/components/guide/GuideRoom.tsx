"use client";

/**
 * The room guide on the room page (decision 0376): the diorama viewer where
 * the room is, the guest's rail beside it, and the guide's moves played in the
 * room as it speaks.
 *
 * Shown instead of RoomStage when ROOM_GUIDE_ENABLED is on and the scene's
 * assets carry a scene_url. The rail is RoomStage's rail in the product's
 * dusk register (decision 0361): the person's words in a bubble, the guest's
 * in the serif's italic (its words are prose), the room's own words on "Show
 * me" cards and in quiet interface notes. The page never decides where
 * anything goes: a card arrives solved and checked, "Show me" asks the server
 * to keep it and plays the plan it returns, "Put it back" plays the way back.
 *
 * A first visit asks for the guest's opening read once the viewer is up. A
 * turn that fails puts back on screen anything it moved (the server kept
 * none of it) and keeps the person's words in the composer.
 *
 * Like the conversation layer it replaces, this is an enhancement: if the
 * guide or the viewer cannot be reached, onUnavailable() hands the room back
 * to RoomStage and the guest it already has.
 */

import { motion } from "motion/react";
import { useCallback, useEffect, useRef, useState } from "react";

import { Mark } from "@/components/Wordmark";
import { SPRING } from "@/components/ui/spring";
import { GuestLine } from "@/components/ui/voice";
import { getApiClient } from "@/lib/api";
import { ApiError, BudgetExhaustedError, TurnInFlightError } from "@/lib/api/client";
import { attachPlayer, playPlan, type GuidePlayer } from "@/lib/guide/player";
import { viewerSrc } from "@/lib/guide/switch";
import {
  cardSentence,
  cardStatus,
  foldEvents,
  noteFor,
  type StreamedEvent,
} from "@/lib/guide/transcript";
import type {
  CardStatus,
  GuideCard,
  GuideItem,
  GuidePose,
  GuideSnapshot,
  GuideState,
  GuideTurnView,
  MotionPlan,
} from "@/lib/guide/types";

const FLUSH_MS = 150;
const BLOCKED_POLL_MS = 5_000;
const REST_POLL_MS = 60_000;

type Phase =
  | { kind: "idle" }
  | { kind: "busy" }
  | { kind: "blocked" }
  | { kind: "rested"; until: number | null; line: string | null };

interface LiveTurn {
  clientMsgId: string;
  person: string | null;
  items: GuideItem[];
}

const EMPTY_ROOM: GuideState = { poses: {}, can_undo: false, cards: {} };

/** Where every piece a plan moved stood before it moved. */
function startPoses(plan: MotionPlan): Record<string, GuidePose> {
  const out: Record<string, GuidePose> = {};
  for (const [pid, keys] of Object.entries(plan.tracks)) {
    const k = keys[0];
    if (k) out[pid] = { x: k.x, y: k.y, z: k.z, yaw: k.yaw };
  }
  return out;
}

function NoteCard({ text }: { text: string }) {
  const cut = text.indexOf(". ");
  const lead = cut === -1 ? text : text.slice(0, cut + 1);
  const rest = cut === -1 ? "" : text.slice(cut + 2);
  return (
    <div role="status" className="rounded-[14px] bg-[#1a232e] px-4 py-3.5 text-[14.5px] leading-[1.5] text-on-dusk">
      <span className="font-semibold text-sun">{lead}</span>
      {rest && ` ${rest}`}
    </div>
  );
}

function Card({
  card,
  status,
  disabled,
  onShow,
}: {
  card: GuideCard;
  status: CardStatus;
  disabled: boolean;
  onShow: (id: string) => void;
}) {
  const label =
    status === "ready" ? "Show me" : status === "shown" ? "On screen" : "The room has moved on";
  return (
    <div className="rounded-[16px] border border-on-dusk/[0.1] bg-dusk-3 px-4 pb-3.5 pt-3">
      <p className="text-[14.5px] leading-[1.45] text-on-dusk">{cardSentence(card)}</p>
      {card.fixes.length > 0 && (
        <ul className="mt-2 space-y-1">
          {card.fixes.map((f) => (
            <li key={f} className="text-[13px] leading-[1.45] text-on-dusk-2">
              {f}
            </li>
          ))}
        </ul>
      )}
      {card.adds.length > 0 && (
        <p className="mt-2 text-[13px] leading-[1.45] text-on-dusk-2">{`It brings: ${card.adds.join(" ")}`}</p>
      )}
      <div className="mt-3 flex items-center justify-between gap-3">
        <span className="text-[12.5px] text-on-dusk-2">{card.effort.charAt(0).toUpperCase() + card.effort.slice(1)}</span>
        <button
          type="button"
          onClick={() => onShow(card.id)}
          disabled={disabled || status !== "ready"}
          className="inline-flex h-8 shrink-0 cursor-pointer items-center rounded-full bg-on-dusk px-4 text-[13px] font-semibold text-dusk transition-colors hover:bg-white disabled:cursor-default disabled:bg-on-dusk/15 disabled:text-on-dusk/50"
        >
          {label}
        </button>
      </div>
    </div>
  );
}

function Items({
  items,
  statuses,
  disabled,
  onShow,
  caret = false,
}: {
  items: GuideItem[];
  statuses: Record<string, CardStatus>;
  disabled: boolean;
  onShow: (id: string) => void;
  caret?: boolean;
}) {
  return (
    <>
      {items.map((item, i) => {
        const last = i === items.length - 1;
        if (item.kind === "say") {
          return (
            <GuestLine key={i} tone="cream" className="text-[17.5px] leading-[1.5]">
              {item.text}
              {caret && last && (
                <span aria-hidden className="gg-caret ml-0.5 inline-block h-[1.05em] w-0.5 bg-sun align-[-2px]" />
              )}
            </GuestLine>
          );
        }
        if (item.kind === "note") {
          return (
            <p key={i} className="text-[13px] leading-[1.45] text-on-dusk-2">
              {item.text}
            </p>
          );
        }
        return (
          <Card
            key={`${item.card.id}-${i}`}
            card={item.card}
            status={cardStatus(item.card, statuses)}
            disabled={disabled}
            onShow={onShow}
          />
        );
      })}
    </>
  );
}

const YOU =
  "ml-auto max-w-[86%] rounded-[18px_18px_6px_18px] bg-dusk-3 px-4 py-2.5 text-[15px] leading-[1.45] text-on-dusk";

export default function GuideRoom({
  sceneId,
  sceneUrl,
  onUnavailable,
  onFloorArea,
}: {
  sceneId: string;
  sceneUrl: string;
  /** The guide or the viewer cannot be reached: hand the room back. */
  onUnavailable: () => void;
  /** The room's floor area as the top bar prints it, as RoomStage's onMeasure. */
  onFloorArea?: (text: string) => void;
}) {
  const [src, setSrc] = useState<string | null>(null);
  const [turns, setTurns] = useState<GuideTurnView[]>([]);
  const [room, setRoom] = useState<GuideState>(EMPTY_ROOM);
  const [live, setLive] = useState<LiveTurn | null>(null);
  const [phase, setPhase] = useState<Phase>({ kind: "idle" });
  const [draft, setDraft] = useState("");
  const [note, setNote] = useState<string | null>(null);
  const [moving, setMoving] = useState(false);
  const [viewerReady, setViewerReady] = useState(false);

  const frameRef = useRef<HTMLIFrameElement>(null);
  const playerRef = useRef<GuidePlayer | null>(null);
  const logRef = useRef<HTMLDivElement>(null);
  const mounted = useRef(true);
  // A first visit's opening, asked for once: effects can run again (Fast
  // Refresh, a remount) and the server refuses a second opening anyway.
  const wantsOpening = useRef(false);
  const keptPoses = useRef<Record<string, GuidePose>>({});
  const unavailable = useRef(onUnavailable);
  const floorArea = useRef(onFloorArea);
  useEffect(() => {
    unavailable.current = onUnavailable;
    floorArea.current = onFloorArea;
  });

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  // The conversation so far, and the room as it stands. Any failure hands
  // the room back to RoomStage.
  const applySnapshot = useCallback((snap: GuideSnapshot) => {
    setTurns(snap.transcript);
    setRoom(snap.state);
    floorArea.current?.(`${snap.floor_m2.toFixed(1)} m²`);
    const until = snap.rested_until ? new Date(snap.rested_until).getTime() : null;
    if (until !== null) setPhase({ kind: "rested", until, line: null });
    else if (snap.busy) setPhase({ kind: "blocked" });
    else setPhase({ kind: "idle" });
    return snap;
  }, []);

  useEffect(() => {
    let cancelled = false;
    getApiClient()
      .getGuide(sceneId)
      .then((snap) => {
        if (cancelled) return;
        applySnapshot(snap);
        keptPoses.current = snap.state.poses;
        wantsOpening.current = snap.turn_count === 0 && !snap.busy && !snap.rested_until;
        setSrc(viewerSrc(sceneUrl, Object.keys(snap.state.poses).length > 0));
      })
      .catch(() => {
        if (!cancelled) unavailable.current();
      });
    return () => {
      cancelled = true;
    };
  }, [sceneId, sceneUrl, applySnapshot]);

  // One turn: the guest's words as they are written, cards, moves played in
  // order, and on failure the room put back as the server kept it.
  const runTurn = useCallback(
    async (turn: { text?: string; opening?: boolean }) => {
      const clientMsgId = crypto.randomUUID();
      const person = turn.opening ? null : (turn.text ?? "");
      // Any turn makes the opening moot: a person who speaks first is answered.
      wantsOpening.current = false;
      const events: StreamedEvent[] = [];
      const played: MotionPlan[] = [];
      const flush = () => {
        if (!mounted.current) return;
        setLive((l) => (l && l.clientMsgId === clientMsgId ? { ...l, items: foldEvents(events) } : l));
      };
      setNote(null);
      setLive({ clientMsgId, person, items: [] });
      setPhase({ kind: "busy" });
      const timer = window.setInterval(flush, FLUSH_MS);
      const fail = async (code: string) => {
        // Nothing of the turn was kept, so nothing it moved stays moved.
        const player = playerRef.current;
        if (player && played.length) {
          player.clear();
          for (const plan of [...played].reverse()) await player.place(startPoses(plan));
        }
        if (!mounted.current) return;
        setLive(null);
        if (person) setDraft(person);
        if (code === "budget_exhausted") {
          setPhase({ kind: "rested", until: null, line: null });
        } else {
          setPhase({ kind: "idle" });
        }
        setNote(noteFor(code));
      };
      try {
        const stream = await getApiClient().sendGuideTurn(sceneId, turn, clientMsgId);
        for await (const ev of stream) {
          if (!mounted.current) return;
          if (ev.type === "delta" || ev.type === "note") {
            events.push(ev);
          } else if (ev.type === "card") {
            events.push(ev);
            setRoom((r) => ({ ...r, cards: { ...r.cards, [ev.card.id]: ev.card.status ?? "ready" } }));
            flush();
          } else if (ev.type === "focus") {
            events.push(ev);
            playerRef.current?.show(ev.focus);
          } else if (ev.type === "play") {
            events.push(ev);
            flush();
            if (ev.plan) played.push(ev.plan);
            await playPlan(playerRef.current, ev.plan);
            if (mounted.current) setRoom(ev.state);
          } else if (ev.type === "done") {
            flush();
            keptPoses.current = ev.state.poses;
            setTurns((ts) => [
              ...ts.filter((t) => t.client_msg_id !== clientMsgId),
              { turn_index: ev.turnIndex, client_msg_id: clientMsgId, opening: !person, person, items: foldEvents(events) },
            ]);
            setRoom(ev.state);
            setLive(null);
            setPhase({ kind: "idle" });
            return;
          } else {
            await fail(ev.code);
            return;
          }
        }
        await fail("connection_lost");
      } catch (exc: unknown) {
        if (!mounted.current) return;
        setLive(null);
        if (person) setDraft(person);
        if (exc instanceof BudgetExhaustedError) {
          setPhase({
            kind: "rested",
            until: exc.resetsAt ? new Date(exc.resetsAt).getTime() : null,
            line: exc.guestLine,
          });
        } else if (exc instanceof TurnInFlightError) {
          setPhase({ kind: "blocked" });
        } else if (exc instanceof ApiError && exc.code === "already_open") {
          setPhase({ kind: "idle" });
        } else {
          setPhase({ kind: "idle" });
          setNote(noteFor(exc instanceof ApiError ? exc.code : "connection_lost"));
        }
      } finally {
        window.clearInterval(timer);
      }
    },
    [sceneId],
  );

  // The viewer: its player is injected once the room is drawn, the kept
  // arrangement placed, and a first visit asks for the guest's opening.
  useEffect(() => {
    const frame = frameRef.current;
    if (!src || !frame) return;
    const abort = new AbortController();
    attachPlayer(frame, { signal: abort.signal })
      .then(async (player) => {
        if (abort.signal.aborted) return;
        playerRef.current = player;
        if (Object.keys(keptPoses.current).length) await player.place(keptPoses.current);
        if (!mounted.current) return;
        setViewerReady(true);
        if (wantsOpening.current) {
          wantsOpening.current = false;
          void runTurn({ opening: true });
        }
      })
      .catch(() => {
        if (!abort.signal.aborted) unavailable.current();
      });
    return () => abort.abort();
  }, [src, runTurn]);

  // Blocked by another window, or resting: look again on a slow tick.
  useEffect(() => {
    if (phase.kind !== "blocked" && phase.kind !== "rested") return;
    const rested = phase.kind === "rested";
    const timer = window.setInterval(() => {
      if (rested && phase.until !== null && Date.now() < phase.until) return;
      getApiClient()
        .getGuide(sceneId)
        .then((snap) => {
          if (mounted.current) applySnapshot(snap);
        })
        .catch(() => undefined);
    }, rested ? REST_POLL_MS : BLOCKED_POLL_MS);
    return () => window.clearInterval(timer);
  }, [phase, sceneId, applySnapshot]);

  // The newest words are always in view.
  useEffect(() => {
    const log = logRef.current;
    if (log) log.scrollTop = log.scrollHeight;
  }, [turns, live, note, phase]);

  const press = useCallback(
    async (act: () => Promise<{ plan: MotionPlan | null; state: GuideState }>) => {
      setMoving(true);
      setNote(null);
      try {
        const move = await act();
        await playPlan(playerRef.current, move.plan);
        if (!mounted.current) return;
        keptPoses.current = move.state.poses;
        setRoom(move.state);
      } catch (exc: unknown) {
        if (!mounted.current) return;
        const code = exc instanceof ApiError ? exc.code : "connection_lost";
        setNote(noteFor(code));
        // The server's word on the cards is the truth; read it again.
        getApiClient()
          .getGuide(sceneId)
          .then((snap) => {
            if (mounted.current) setRoom(snap.state);
          })
          .catch(() => undefined);
      } finally {
        if (mounted.current) setMoving(false);
      }
    },
    [sceneId],
  );

  const showCard = useCallback(
    (id: string) => void press(() => getApiClient().showGuideCard(sceneId, id)),
    [press, sceneId],
  );
  const putBack = useCallback(
    () => void press(() => getApiClient().undoGuide(sceneId)),
    [press, sceneId],
  );

  const busy = phase.kind === "busy";
  const composerDisabled = busy || moving || phase.kind === "rested" || phase.kind === "blocked";
  const send = () => {
    const text = draft.trim();
    if (!text || composerDisabled) return;
    setDraft("");
    void runTurn({ text });
  };

  return (
    <div className="absolute inset-0">
      {/* The room, left of the rail on wide screens, as RoomStage draws it. */}
      <div className="absolute inset-0 bg-dusk lg:right-[460px]">
        {src && (
          <iframe
            ref={frameRef}
            src={src}
            title="Your room, as a model you can rearrange"
            className={`h-full w-full border-0 transition-opacity duration-500 ${viewerReady ? "opacity-100" : "opacity-0"}`}
          />
        )}
        {/* The page's chrome is drawn for dusk and the viewer's daylight
            backdrop is pale: a shade of dusk under the room's name keeps it
            legible without touching the viewer. */}
        <div
          aria-hidden
          className="pointer-events-none absolute inset-x-0 top-0 h-36"
          style={{
            background:
              "linear-gradient(to bottom, rgba(13,20,28,0.88) 0%, rgba(13,20,28,0.5) 55%, rgba(13,20,28,0) 100%)",
          }}
        />
        {!viewerReady && (
          <div className="pointer-events-none absolute inset-0 flex items-center justify-center px-6">
            <p className="text-sm text-on-dusk-2">Opening the door…</p>
          </div>
        )}
      </div>

      <aside
        aria-label="Conversation with the guest"
        className="absolute inset-x-3 bottom-3 z-20 flex max-h-[48%] flex-col overflow-hidden rounded-3xl border border-on-dusk/[0.08] bg-dusk-2 lg:inset-x-auto lg:bottom-4 lg:right-4 lg:top-4 lg:max-h-none lg:w-[428px]"
      >
        <div className="flex items-center justify-between gap-3 px-6 pb-3 pt-5">
          <div className="flex items-center gap-2.5">
            <Mark height="13px" />
            <h2 className="text-[15px] font-semibold text-on-dusk">The guest</h2>
          </div>
          <span className="text-[13px] text-on-dusk-2">Moves only what the room has checked</span>
        </div>

        {/* What is on screen is not the scan: the way back is one control. */}
        {room.can_undo && (
          <div className="px-4 pb-2">
            <div className="flex items-center justify-between gap-4 rounded-[14px] bg-dusk-3 px-4 py-2.5">
              <p className="text-[13px] leading-snug text-on-dusk">The room on screen has changed.</p>
              <button
                type="button"
                onClick={putBack}
                disabled={moving || busy}
                className="shrink-0 cursor-pointer rounded-full px-3 py-1.5 text-[12.5px] font-medium text-on-dusk ring-1 ring-inset ring-on-dusk/25 transition-colors hover:bg-dusk disabled:cursor-default disabled:opacity-50"
              >
                Put it back
              </button>
            </div>
          </div>
        )}

        <div ref={logRef} className="min-h-0 flex-1 overflow-y-auto px-6 pb-4 pt-2" aria-live="polite">
          <div className="flex flex-col gap-3">
            {turns.map((t) => (
              <div key={t.client_msg_id} className="flex flex-col gap-3">
                {t.person && <p className={YOU}>{t.person}</p>}
                <Items items={t.items} statuses={room.cards} disabled={moving || busy} onShow={showCard} />
              </div>
            ))}

            {live && (
              <motion.div
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                transition={SPRING}
                className="flex flex-col gap-3"
              >
                {live.person && <p className={YOU}>{live.person}</p>}
                <Items items={live.items} statuses={room.cards} disabled onShow={showCard} caret />
                {live.items.length === 0 && (
                  <p role="status" aria-label="The guest is thinking" className="flex h-[27px] items-center gap-1.5">
                    {[0, 1, 2].map((i) => (
                      <span key={i} aria-hidden className="gg-dot h-[7px] w-[7px] rounded-full bg-on-dusk" />
                    ))}
                  </p>
                )}
              </motion.div>
            )}

            {phase.kind === "rested" &&
              (phase.line ? (
                <GuestLine tone="cream" className="text-[17.5px] leading-[1.5]">
                  {phase.line}
                </GuestLine>
              ) : (
                <p className="text-[14px] leading-[1.5] text-on-dusk-2">
                  The guest is resting for now. The room stays open, and the conversation picks back up a little later.
                </p>
              ))}
            {phase.kind === "blocked" && (
              <p className="text-[14px] leading-[1.5] text-on-dusk-2">
                This room is mid-thought in another window. When that answer lands, this one frees up on its own.
              </p>
            )}
            {note && <NoteCard text={note} />}
          </div>
        </div>

        <div className="border-t border-on-dusk/[0.07] px-4 pb-4 pt-3.5">
          <form
            className={`flex items-center gap-2 rounded-full border border-on-dusk/[0.12] bg-dusk py-1.5 pl-5 pr-1.5 transition-opacity ${
              composerDisabled ? "opacity-60" : ""
            }`}
            onSubmit={(e) => {
              e.preventDefault();
              send();
            }}
          >
            <label htmlFor="ask-guide" className="sr-only">
              Ask the guest about this room
            </label>
            <input
              id="ask-guide"
              type="text"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              disabled={composerDisabled}
              maxLength={2000}
              placeholder={
                phase.kind === "rested"
                  ? "Resting for now"
                  : phase.kind === "blocked"
                    ? "One voice at a time"
                    : "Ask about this room"
              }
              className="h-10 min-w-0 flex-1 bg-transparent text-[15px] text-on-dusk outline-none placeholder:text-[#97a3b1] disabled:cursor-not-allowed"
            />
            <button
              type="submit"
              disabled={composerDisabled || !draft.trim()}
              aria-label="Send"
              className="grid h-10 w-10 shrink-0 cursor-pointer place-items-center rounded-full bg-on-dusk text-dusk transition-colors hover:bg-white disabled:cursor-default disabled:bg-on-dusk/15 disabled:text-on-dusk/40"
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                <path d="M12 19V5" />
                <path d="M6 11l6-6 6 6" />
              </svg>
            </button>
          </form>
        </div>
      </aside>
    </div>
  );
}
