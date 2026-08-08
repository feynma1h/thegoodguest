"use client";

/**
 * The live conversation surface (decision 0058): the narration card + the
 * real composer, replacing the disabled one on a ready room. Owns the
 * transcript, drives the pure composer reducer (lib/conversation/reducer),
 * and speaks only through the ApiClient's GuestEvent seam — mock and live
 * are indistinguishable from here.
 *
 * Delta arrival: raw deltas accumulate in a ref OUTSIDE React state and
 * flush on a ~200 ms batch timer (calm arrival and render economy are one
 * mechanism); under prefers-reduced-motion, flushes wait for sentence
 * boundaries. All entrances ride the single SPRING. Nothing here is gold.
 *
 * The card carries the current exchange; earlier exchanges collapse to
 * stubs labeled with the user's own truncated words, tap-to-expand. No
 * truncation note is ever shown — the record is exactly what was said.
 *
 * Conversation is an enhancement layer: if the initial GET fails
 * (403/404/network), onUnavailable() fires and the room page falls back to
 * the non-conversational settled layout — the room never breaks.
 */

import { motion } from "motion/react";
import {
  useCallback,
  useEffect,
  useReducer,
  useRef,
  useState,
} from "react";

import { SPRING } from "@/components/ui/spring";
import { GuestLine } from "@/components/ui/voice";
import { getApiClient } from "@/lib/api";
import {
  ApiError,
  BudgetExhaustedError,
  TurnInFlightError,
} from "@/lib/api/client";
import type { ConversationTurn, GuestEvent } from "@/lib/api/types";
import {
  COMPOSER_IDLE,
  composerReducer,
  splitAtSentenceBoundary,
  type ComposerState,
} from "@/lib/conversation/reducer";

const FLUSH_MS = 200;
const CONFIRM_POLL_MS = 4_000;
const BLOCKED_POLL_MS = 5_000;
const REST_POLL_MS = 15_000;
const STUB_CHARS = 44;

/** Quiet, non-voice notes (sans, never italic serif — the guest didn't say
 * these; the interface did). */
const NOTES: Record<string, string> = {
  connection_lost: "That didn't reach the room — your words are kept below.",
  model_timeout: "The guest lost the thread mid-sentence. Your words are kept — send them again when you're ready.",
  model_unavailable: "The guest couldn't be reached just now. Your words are kept — try again in a moment.",
  model_error: "Something went wrong on the way back. Your words are kept — send them again when you're ready.",
  persist_failed: "The reply couldn't be kept, so it doesn't count as said. Your words are below — send them again.",
  turn_failed: "That one didn't come together. Your words are kept — send them again when you're ready.",
  upstream_error: "The room's records couldn't be reached. Your words are kept — try again in a moment.",
};

function noteFor(code: string): string {
  return NOTES[code] ?? NOTES.turn_failed;
}

function stubLabel(text: string): string {
  const oneLine = text.replace(/\s+/g, " ").trim();
  return oneLine.length <= STUB_CHARS ? oneLine : `${oneLine.slice(0, STUB_CHARS)}…`;
}

function prefersReducedMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

export default function Conversation({
  sceneId,
  greeting,
  countsNote,
  onUnavailable,
  onArrangementChanged,
}: {
  sceneId: string;
  greeting: string;
  countsNote: string | null;
  onUnavailable: () => void;
  /** The guest changed the room (decision 0131). Fires mid-stream, before
   * the speech describing it, so the piece moves while the sentence about
   * it is still arriving — which is the right order: the room is the
   * subject, the guest is narrating it. */
  onArrangementChanged?: () => void;
}) {
  const [state, dispatch] = useReducer(composerReducer, COMPOSER_IDLE);
  const [turns, setTurns] = useState<ConversationTurn[] | null>(null);
  const [expanded, setExpanded] = useState<number | null>(null);
  const mounted = useRef(true);
  const stateRef = useRef<ComposerState>(COMPOSER_IDLE);
  // Read at call time so a changing callback identity never re-creates the
  // turn runner (the same pattern SplatViewer uses for its reveal hooks).
  const onArrangementRef = useRef(onArrangementChanged);
  useEffect(() => {
    onArrangementRef.current = onArrangementChanged;
  });

  useEffect(() => {
    stateRef.current = state;
  }, [state]);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const mergeTurns = useCallback((incoming: ConversationTurn[]) => {
    setTurns((prev) => {
      const byIndex = new Map((prev ?? []).map((t) => [t.turn_index, t]));
      for (const t of incoming) byIndex.set(t.turn_index, t);
      return [...byIndex.values()].sort((a, b) => a.turn_index - b.turn_index);
    });
  }, []);

  // Initial snapshot. Failure of any kind degrades to the
  // non-conversational settled layout via onUnavailable.
  useEffect(() => {
    let cancelled = false;
    getApiClient()
      .getConversation(sceneId)
      .then((snapshot) => {
        if (cancelled) return;
        mergeTurns(snapshot.turns);
        setTurns((prev) => prev ?? []);
        const rested = snapshot.conversation.rested_until;
        if (rested && new Date(rested).getTime() > Date.now()) {
          dispatch({
            type: "PRE_STREAM_BUDGET",
            guestLine: null,
            restedUntil: new Date(rested).getTime(),
          });
        }
      })
      .catch(() => {
        if (!cancelled) onUnavailable();
      });
    return () => {
      cancelled = true;
    };
  }, [sceneId, mergeTurns, onUnavailable]);

  // Drive one turn: consume the GuestEvent iterable, batching deltas
  // outside React state and flushing every ~200 ms (sentence boundaries
  // under reduced motion).
  const runTurn = useCallback(
    async (text: string, clientMsgId: string) => {
      const buffer = { current: "" };
      const flush = (all: boolean) => {
        if (!buffer.current) return;
        let out = buffer.current;
        if (!all && prefersReducedMotion()) {
          const [head, tail] = splitAtSentenceBoundary(buffer.current);
          if (!head) return;
          out = head;
          buffer.current = tail;
        } else {
          buffer.current = "";
        }
        if (mounted.current) dispatch({ type: "STREAM_DELTA", text: out });
      };
      const timer = window.setInterval(() => flush(false), FLUSH_MS);
      try {
        const events: AsyncIterable<GuestEvent> = await getApiClient().sendMessage(
          sceneId,
          text,
          clientMsgId,
        );
        for await (const event of events) {
          if (!mounted.current) return;
          if (event.type === "delta") {
            buffer.current += event.text;
          } else if (event.type === "arrangement") {
            // Deliberately outside the composer reducer: the arrangement is
            // the ROOM's state, not the composer's, and giving the reducer
            // an opinion about it would make two components own one fact.
            onArrangementRef.current?.();
          } else if (event.type === "done") {
            flush(true);
            mergeTurns([event.turn]);
            dispatch({ type: "STREAM_DONE", turn: event.turn });
            return;
          } else if (event.type === "error") {
            flush(true);
            if (event.code === "connection_lost") {
              dispatch({ type: "CONNECTION_LOST" });
            } else {
              dispatch({ type: "STREAM_ERROR", code: event.code });
            }
            return;
          }
        }
        if (mounted.current) dispatch({ type: "CONNECTION_LOST" });
      } catch (exc: unknown) {
        if (!mounted.current) return;
        if (exc instanceof BudgetExhaustedError) {
          dispatch({
            type: "PRE_STREAM_BUDGET",
            guestLine: exc.guestLine,
            restedUntil: exc.resetsAt ? new Date(exc.resetsAt).getTime() : null,
          });
        } else if (exc instanceof TurnInFlightError) {
          dispatch({ type: "PRE_STREAM_IN_FLIGHT", now: Date.now() });
        } else if (exc instanceof ApiError) {
          dispatch({ type: "PRE_STREAM_FAILED", code: exc.code });
        } else {
          dispatch({ type: "CONNECTION_LOST" });
        }
      } finally {
        window.clearInterval(timer);
      }
    },
    [sceneId, mergeTurns],
  );

  const submit = useCallback(() => {
    const current = stateRef.current;
    if (current.phase !== "idle" && current.phase !== "reoffer") return;
    if (!current.draft.trim()) return;
    const clientMsgId = crypto.randomUUID();
    dispatch({ type: "SUBMIT", clientMsgId, now: Date.now() });
    void runTurn(current.draft, clientMsgId);
  }, [runTurn]);

  // Confirming: the stream died without a terminal event — refetch by
  // client_msg_id on a spaced cadence until found or the window lapses.
  const confirmingId = state.phase === "confirming" ? state.clientMsgId : null;
  useEffect(() => {
    if (confirmingId === null) return;
    let cancelled = false;
    const check = () => {
      getApiClient()
        .getConversation(sceneId)
        .then((snapshot) => {
          if (cancelled || !mounted.current) return;
          const found = snapshot.turns.find(
            (t) => t.client_msg_id === confirmingId,
          );
          if (found) {
            mergeTurns(snapshot.turns);
            dispatch({ type: "CONFIRM_FOUND", turn: found });
          } else {
            dispatch({ type: "CONFIRM_NOT_FOUND", now: Date.now() });
          }
        })
        .catch(() => {
          if (!cancelled && mounted.current) {
            dispatch({ type: "CONFIRM_NOT_FOUND", now: Date.now() });
          }
        });
    };
    check();
    const timer = window.setInterval(check, CONFIRM_POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [confirmingId, sceneId, mergeTurns]);

  // Blocked (second tab): spaced refetches until the other tab's turn lands.
  useEffect(() => {
    if (state.phase !== "blocked") return;
    const known = turns?.length ?? 0;
    let cancelled = false;
    const timer = window.setInterval(() => {
      getApiClient()
        .getConversation(sceneId)
        .then((snapshot) => {
          if (cancelled || !mounted.current) return;
          if (snapshot.turns.length > known || snapshot.conversation.turn_count > known) {
            mergeTurns(snapshot.turns);
            dispatch({ type: "OTHER_TAB_SETTLED" });
          }
        })
        .catch(() => undefined);
    }, BLOCKED_POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [state.phase, sceneId, turns?.length, mergeTurns]);

  // Rested: wake when restedUntil passes (checked on a slow tick).
  const restedUntil = state.phase === "rested" ? state.restedUntil : null;
  useEffect(() => {
    if (restedUntil === null) return;
    const timer = window.setInterval(() => {
      if (Date.now() >= restedUntil) dispatch({ type: "REST_ELAPSED" });
    }, REST_POLL_MS);
    return () => window.clearInterval(timer);
  }, [restedUntil]);

  if (turns === null) {
    // Snapshot still loading: hold the layout without claiming anything.
    return (
      <div className="rounded-[14px] border border-ink/15 bg-paper/[0.96] px-5 py-4 shadow-deep">
        <GuestLine className="text-[15px] opacity-50">{greeting}</GuestLine>
      </div>
    );
  }

  const inFlight =
    state.phase === "submitting" ||
    state.phase === "streaming" ||
    state.phase === "confirming";
  const latest = turns.length > 0 ? turns[turns.length - 1] : null;
  // Stubs: every earlier exchange; while a new exchange is in flight, the
  // latest completed turn is "earlier" too.
  const stubs = inFlight || state.phase === "reoffer" ? turns : turns.slice(0, -1);

  const composerDisabled =
    inFlight || state.phase === "rested" || state.phase === "blocked";
  const draft =
    state.phase === "idle" || state.phase === "reoffer" ? state.draft : "";

  return (
    <div className="w-full">
      {/* Earlier exchanges: the user's own words, truncated, tap-to-expand. */}
      {stubs.length > 0 && (
        <ul className="mb-2 max-h-[26vh] space-y-1 overflow-y-auto pr-1">
          {stubs.map((turn) => (
            <li key={turn.turn_index}>
              <button
                type="button"
                onClick={() =>
                  setExpanded(expanded === turn.turn_index ? null : turn.turn_index)
                }
                className="w-full rounded-lg bg-paper/80 px-3.5 py-1.5 text-left shadow-float transition-colors hover:bg-paper/95"
              >
                <span className="block truncate text-[12px] text-ink/60">
                  {stubLabel(turn.user_text)}
                </span>
                {expanded === turn.turn_index && (
                  <span className="mt-1.5 block border-t border-ink/10 pt-1.5">
                    <span className="block text-[12.5px] text-ink/75">
                      {turn.user_text}
                    </span>
                    <GuestLine className="mt-1 text-[13px]">
                      {turn.assistant_text}
                    </GuestLine>
                  </span>
                )}
              </button>
            </li>
          ))}
        </ul>
      )}

      {/* The card: the current exchange. Entrance-only springs — exit
          choreography would hold the card hostage to animation completion
          (mode="wait" freezes under throttled rAF), and the design only
          asks entrances to ride the SPRING. */}
      <div className="rounded-[14px] border border-ink/15 bg-paper/[0.96] px-5 py-4 shadow-deep">
        <motion.div
          key={`${state.phase}-${latest?.turn_index ?? "none"}`}
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={SPRING}
        >
            {inFlight ? (
              <>
                <p className="text-[12.5px] text-ink/60">{state.draft}</p>
                {state.phase === "streaming" && state.partial ? (
                  <GuestLine className="mt-2 text-[15px]">
                    {state.partial}
                  </GuestLine>
                ) : state.phase === "confirming" ? (
                  <p className="mt-2 text-[12.5px] text-ink/50">
                    Making sure that reached the room…
                  </p>
                ) : (
                  <p className="mt-2 text-[15px] text-ink/40" aria-label="the guest is thinking">
                    <span className="breathe inline-block">…</span>
                  </p>
                )}
              </>
            ) : state.phase === "reoffer" ? (
              <>
                {latest && (
                  <GuestLine className="mb-2 text-[14px] opacity-70">
                    {latest.assistant_text}
                  </GuestLine>
                )}
                <p className="text-[12.5px] text-ink/60">{noteFor(state.code)}</p>
              </>
            ) : state.phase === "rested" ? (
              state.guestLine ? (
                <GuestLine className="text-[15px]">{state.guestLine}</GuestLine>
              ) : (
                <p className="text-[13px] text-ink/60">
                  The guest is resting for now — the room stays open, and the
                  conversation picks back up a little later.
                </p>
              )
            ) : state.phase === "blocked" ? (
              <p className="text-[13px] text-ink/60">
                This room is mid-thought in another window. When that reply
                lands, this one frees up on its own.
              </p>
            ) : latest ? (
              <>
                <p className="text-[12.5px] text-ink/60">{latest.user_text}</p>
                <GuestLine className="mt-2 text-[15px]">
                  {latest.assistant_text}
                </GuestLine>
              </>
            ) : (
              <>
                <GuestLine className="text-[15px]">{greeting}</GuestLine>
                {countsNote && (
                  <p className="mt-2 text-[11.5px] text-ink/55">{countsNote}</p>
                )}
              </>
            )}
          </motion.div>
      </div>

      {/* The composer — alive. */}
      <form
        className={`mx-auto mt-3 flex max-w-xl items-center gap-3 rounded-full bg-white/95 py-2.5 pl-5 pr-2.5 shadow-float transition-opacity ${
          composerDisabled ? "opacity-60" : ""
        }`}
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <input
          type="text"
          value={draft}
          onChange={(e) => dispatch({ type: "EDIT", draft: e.target.value })}
          disabled={composerDisabled}
          maxLength={2000}
          placeholder={
            state.phase === "rested"
              ? "resting"
              : state.phase === "blocked"
                ? "one voice at a time"
                : "ask about this room"
          }
          className="min-w-0 flex-1 bg-transparent text-sm text-ink outline-none placeholder:text-ink/40 disabled:cursor-not-allowed"
        />
        <button
          type="submit"
          disabled={composerDisabled || !draft.trim()}
          aria-label={state.phase === "reoffer" ? "send again" : "send"}
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-accent font-semibold text-paper transition-colors hover:bg-accent-deep disabled:bg-ink/10 disabled:text-ink/30"
        >
          ↑
        </button>
      </form>
    </div>
  );
}
