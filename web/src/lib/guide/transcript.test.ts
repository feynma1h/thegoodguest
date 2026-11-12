import { describe, expect, it } from "vitest";

import { cardSentence, cardStatus, foldEvents, noteFor, type StreamedEvent } from "./transcript";
import type { GuideCard } from "./types";

const card = (over: Partial<GuideCard> = {}): GuideCard => ({
  id: "p1",
  words: ["the office chair goes to the white desk, set at its front"],
  fixes: [],
  adds: [],
  leaves: [],
  effort: "quick to do",
  goal: "general",
  better: 0.4,
  ...over,
});

describe("foldEvents", () => {
  it("keeps a turn the way the server keeps it (guide_session.fold_events)", () => {
    // The same events as the server's test_a_turn_folds_into_paragraphs_cards_and_notes.
    const events: StreamedEvent[] = [
      { type: "note", text: "Looking…" },
      { type: "delta", text: "The desk " },
      { type: "delta", text: "faces the wall." },
      { type: "card", card: card({ words: ["w"], status: "ready" }) },
      { type: "delta", text: "Want to see it?" },
      { type: "play", plan: null, state: { poses: {}, can_undo: true, cards: {} } },
      { type: "delta", text: "Done." },
      { type: "focus", focus: {} },
      { type: "delta", text: " There." },
    ];
    expect(foldEvents(events).map((i) => (i.kind === "card" ? `card:${i.card.id}` : `${i.kind}:${i.text}`))).toEqual([
      "note:Looking…",
      "say:The desk faces the wall.",
      "card:p1",
      "say:Want to see it?",
      "say:Done.",
      "say: There.",
    ]);
  });

  it("is empty before anything arrives", () => {
    expect(foldEvents([])).toEqual([]);
  });
});

describe("cards", () => {
  it("say the room's words as one sentence", () => {
    expect(cardSentence(card())).toBe("The office chair goes to the white desk, set at its front.");
    expect(cardSentence(card({ words: ["the bed turns around", "the lamp follows it"] }))).toBe(
      "The bed turns around; the lamp follows it.",
    );
    expect(cardSentence(card({ words: [] }))).toBe("");
  });

  it("take the room's latest word on their button", () => {
    expect(cardStatus(card({ status: "ready" }), { p1: "shown" })).toBe("shown");
    expect(cardStatus(card({ status: "ready" }), {})).toBe("ready");
    expect(cardStatus(card(), {})).toBe("gone");
  });
});

describe("notes", () => {
  it("name what went wrong, and fall back to a plain one", () => {
    expect(noteFor("model_timeout")).toContain("lost the thread");
    expect(noteFor("proposal_stale")).toContain("changed since");
    expect(noteFor("something_new")).toBe(noteFor("turn_failed"));
  });
});
