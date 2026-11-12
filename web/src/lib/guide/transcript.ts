/**
 * The panel's view of a turn while it streams (decision 0376), by the rule the
 * server keeps it with (guide_session.fold_events), so a reload shows exactly
 * what was seen live: the guide's words joined into paragraphs, a move, a card
 * or a note between them starting a new one, cards and notes in order.
 *
 * Also the words the panel itself says when a turn cannot finish: interface
 * notes, never the guest's voice.
 *
 * Read by: components/guide/GuideRoom.tsx.
 */

import type { CardStatus, GuideCard, GuideEvent, GuideItem } from "./types";

/** Only the events a turn's transcript is made of. */
export type StreamedEvent = Extract<GuideEvent, { type: "delta" | "card" | "note" | "play" | "focus" }>;

export function foldEvents(events: StreamedEvent[]): GuideItem[] {
  const items: GuideItem[] = [];
  let prev: StreamedEvent["type"] | null = null;
  for (const ev of events) {
    if (ev.type === "delta") {
      const last = items[items.length - 1];
      if (prev === "delta" && last && last.kind === "say") {
        items[items.length - 1] = { kind: "say", text: last.text + ev.text };
      } else {
        items.push({ kind: "say", text: ev.text });
      }
    } else if (ev.type === "card") {
      items.push({ kind: "card", card: ev.card });
    } else if (ev.type === "note") {
      items.push({ kind: "note", text: ev.text });
    }
    prev = ev.type;
  }
  return items;
}

/** A card's button as of now: the room's latest word on it, else what came
 * with the card. */
export function cardStatus(card: GuideCard, statuses: Record<string, CardStatus>): CardStatus {
  return statuses[card.id] ?? card.status ?? "gone";
}

/** "the office chair goes to the white desk" -> "The office chair goes to the
 * white desk." The room's words, as one sentence. */
export function cardSentence(card: GuideCard): string {
  const text = card.words.join("; ").trim();
  if (!text) return "";
  const sentence = text.charAt(0).toUpperCase() + text.slice(1);
  return /[.!?]$/.test(sentence) ? sentence : `${sentence}.`;
}

const NOTES: Record<string, string> = {
  connection_lost: "That didn’t reach the room. Your words are kept below.",
  model_timeout: "The guest lost the thread. Your words are kept, so send them again when you’re ready.",
  model_unavailable: "The guest couldn’t be reached just now. Your words are kept, so try again in a moment.",
  model_error: "Something went wrong on the way back. Your words are kept, so send them again when you’re ready.",
  model_not_allowed: "The guest isn’t available in this room right now.",
  budget_exhausted: "The guest has talked a lot today. Let’s pick it up again a little later.",
  turn_failed: "That one didn’t come together. Your words are kept, so send them again when you’re ready.",
  upstream_error: "The room’s records couldn’t be reached. Try again in a moment.",
  turn_in_flight: "The guest is answering in another window. This one frees up when that answer lands.",
  proposal_stale: "The room has changed since that was suggested, so it can’t be shown as it was.",
  no_clear_path: "There’s no clear way to move that from where things stand now.",
  nothing_to_undo: "Nothing has been moved yet.",
};

export function noteFor(code: string): string {
  return NOTES[code] ?? NOTES.turn_failed;
}
