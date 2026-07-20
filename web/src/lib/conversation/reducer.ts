/**
 * The composer reducer (decision 0058): a pure state machine — the
 * testable artifact behind the conversation composer. All timing arrives
 * as event payloads (`now` in ms), so tests never touch a clock.
 *
 * Phases:
 *   idle        — draft editable, submit allowed
 *   submitting  — request sent, no delta yet
 *   streaming   — deltas arriving (partial accumulates here; the OWNER
 *                 batches raw deltas outside React and dispatches ~200 ms
 *                 flushes — the reducer just appends what it's given)
 *   confirming  — the stream died without a terminal event; the turn's
 *                 fate is unknown. Refetch by client_msg_id across the
 *                 CONFIRM_WINDOW_MS window (aligned to the server's 150 s
 *                 reservation TTL); found → committed, window elapsed →
 *                 reoffer.
 *   reoffer     — the turn did NOT happen. The text is retained in the
 *                 draft; resending takes a human tap — NEVER auto-resend.
 *   rested      — 429: the guest's fixed line renders as speech and the
 *                 composer rests until restedUntil passes.
 *   blocked     — 409 turn_in_flight (second tab): quiet non-voice note,
 *                 spaced refetches until the other tab's turn appears.
 *                 The local draft survives.
 */

import type { ConversationTurn } from "../api/types";

/** Aligned to the server's reservation TTL (150 s): past it the lease has
 * lapsed and an unpersisted turn can no longer be in flight. */
export const CONFIRM_WINDOW_MS = 150_000;

export type ComposerState =
  | { phase: "idle"; draft: string }
  | { phase: "submitting"; draft: string; clientMsgId: string; sentAt: number }
  | {
      phase: "streaming";
      draft: string;
      clientMsgId: string;
      sentAt: number;
      partial: string;
    }
  | {
      phase: "confirming";
      draft: string;
      clientMsgId: string;
      sentAt: number;
      checks: number;
    }
  | { phase: "reoffer"; draft: string; code: string }
  // guestLine null = rested discovered via GET meta on load (no 429 body
  // delivered a line; the UI shows a quiet non-voice note instead — the
  // client never authors guest speech).
  | { phase: "rested"; guestLine: string | null; restedUntil: number | null }
  | { phase: "blocked"; draft: string; since: number };

export type ComposerEvent =
  | { type: "EDIT"; draft: string }
  | { type: "SUBMIT"; clientMsgId: string; now: number } // human tap only
  | { type: "STREAM_DELTA"; text: string }
  | { type: "STREAM_DONE"; turn: ConversationTurn }
  | { type: "STREAM_ERROR"; code: string } // server-authored terminal event
  | { type: "CONNECTION_LOST" } // stream died without a terminal event
  | {
      type: "PRE_STREAM_BUDGET";
      guestLine: string | null;
      restedUntil: number | null;
    }
  | { type: "PRE_STREAM_IN_FLIGHT"; now: number }
  | { type: "PRE_STREAM_FAILED"; code: string }
  | { type: "CONFIRM_FOUND"; turn: ConversationTurn }
  | { type: "CONFIRM_NOT_FOUND"; now: number }
  | { type: "OTHER_TAB_SETTLED" }
  | { type: "REST_ELAPSED" };

export const COMPOSER_IDLE: ComposerState = { phase: "idle", draft: "" };

export function composerReducer(
  state: ComposerState,
  event: ComposerEvent,
): ComposerState {
  switch (state.phase) {
    case "idle":
      if (event.type === "EDIT") return { phase: "idle", draft: event.draft };
      if (event.type === "SUBMIT" && state.draft.trim()) {
        return {
          phase: "submitting",
          draft: state.draft,
          clientMsgId: event.clientMsgId,
          sentAt: event.now,
        };
      }
      if (event.type === "PRE_STREAM_BUDGET") {
        // Reload while rested: GET meta carries rested_until so a reload
        // can't wake a resting composer (decision 0058).
        return {
          phase: "rested",
          guestLine: event.guestLine,
          restedUntil: event.restedUntil,
        };
      }
      return state;

    case "submitting":
    case "streaming": {
      if (event.type === "STREAM_DELTA") {
        return {
          phase: "streaming",
          draft: state.draft,
          clientMsgId: state.clientMsgId,
          sentAt: state.sentAt,
          partial:
            (state.phase === "streaming" ? state.partial : "") + event.text,
        };
      }
      if (event.type === "STREAM_DONE") return COMPOSER_IDLE;
      if (event.type === "STREAM_ERROR" || event.type === "PRE_STREAM_FAILED") {
        return { phase: "reoffer", draft: state.draft, code: event.code };
      }
      if (event.type === "CONNECTION_LOST") {
        return {
          phase: "confirming",
          draft: state.draft,
          clientMsgId: state.clientMsgId,
          sentAt: state.sentAt,
          checks: 0,
        };
      }
      if (event.type === "PRE_STREAM_BUDGET") {
        return {
          phase: "rested",
          guestLine: event.guestLine,
          restedUntil: event.restedUntil,
        };
      }
      if (event.type === "PRE_STREAM_IN_FLIGHT") {
        return { phase: "blocked", draft: state.draft, since: event.now };
      }
      return state;
    }

    case "confirming":
      if (event.type === "CONFIRM_FOUND") return COMPOSER_IDLE;
      if (event.type === "CONFIRM_NOT_FOUND") {
        if (event.now - state.sentAt > CONFIRM_WINDOW_MS) {
          return {
            phase: "reoffer",
            draft: state.draft,
            code: "connection_lost",
          };
        }
        return { ...state, checks: state.checks + 1 };
      }
      return state;

    case "reoffer":
      if (event.type === "EDIT") {
        return { phase: "reoffer", draft: event.draft, code: state.code };
      }
      if (event.type === "SUBMIT" && state.draft.trim()) {
        // A human tap re-submits with a FRESH clientMsgId (the caller
        // mints it) — the old turn provably never happened.
        return {
          phase: "submitting",
          draft: state.draft,
          clientMsgId: event.clientMsgId,
          sentAt: event.now,
        };
      }
      return state;

    case "rested":
      if (event.type === "REST_ELAPSED") return COMPOSER_IDLE;
      return state; // the composer rests — submits and edits are ignored

    case "blocked":
      if (event.type === "OTHER_TAB_SETTLED") {
        return { phase: "idle", draft: state.draft }; // draft survives
      }
      return state;
  }
}

/** Split point for reduced-motion delta flushing: everything through the
 * last sentence boundary flushes; the tail stays buffered. */
export function splitAtSentenceBoundary(buffer: string): [string, string] {
  const match = buffer.match(/^[\s\S]*[.!?…](?=\s|$)/);
  if (!match) return ["", buffer];
  return [match[0], buffer.slice(match[0].length)];
}
