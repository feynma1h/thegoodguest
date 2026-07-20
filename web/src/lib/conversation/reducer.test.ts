/**
 * Composer reducer tests (decision 0058). Pinned invariants: the full
 * transition surface — including the confirming→reoffer timing window and
 * the human-tap-only reoffer contract — plus delta accumulation and the
 * reduced-motion sentence-boundary splitter.
 */
import { describe, expect, it } from "vitest";

import type { ConversationTurn } from "../api/types";
import {
  COMPOSER_IDLE,
  CONFIRM_WINDOW_MS,
  composerReducer,
  splitAtSentenceBoundary,
  type ComposerState,
} from "./reducer";

const T0 = 1_000_000;

const TURN: ConversationTurn = {
  turn_index: 0,
  client_msg_id: "cmid-1",
  user_text: "how does it sit?",
  assistant_text: "Well.",
  created_at: "2026-07-21T12:00:00Z",
};

function submitted(draft = "how does it sit?"): ComposerState {
  return composerReducer(
    { phase: "idle", draft },
    { type: "SUBMIT", clientMsgId: "cmid-1", now: T0 },
  );
}

describe("idle", () => {
  it("edits the draft", () => {
    const s = composerReducer(COMPOSER_IDLE, { type: "EDIT", draft: "hi" });
    expect(s).toEqual({ phase: "idle", draft: "hi" });
  });

  it("submits a non-empty draft", () => {
    expect(submitted()).toEqual({
      phase: "submitting",
      draft: "how does it sit?",
      clientMsgId: "cmid-1",
      sentAt: T0,
    });
  });

  it("refuses to submit whitespace", () => {
    const s = composerReducer(
      { phase: "idle", draft: "   " },
      { type: "SUBMIT", clientMsgId: "x", now: T0 },
    );
    expect(s.phase).toBe("idle");
  });

  it("a reload while rested cannot wake the composer (GET meta path)", () => {
    const s = composerReducer(COMPOSER_IDLE, {
      type: "PRE_STREAM_BUDGET",
      guestLine: null,
      restedUntil: T0 + 1000,
    });
    expect(s).toEqual({ phase: "rested", guestLine: null, restedUntil: T0 + 1000 });
  });
});

describe("streaming", () => {
  it("accumulates deltas across submitting → streaming", () => {
    let s = submitted();
    s = composerReducer(s, { type: "STREAM_DELTA", text: "The sofa " });
    s = composerReducer(s, { type: "STREAM_DELTA", text: "holds." });
    expect(s).toMatchObject({ phase: "streaming", partial: "The sofa holds." });
  });

  it("done returns to a cleared idle", () => {
    let s = submitted();
    s = composerReducer(s, { type: "STREAM_DELTA", text: "x" });
    s = composerReducer(s, { type: "STREAM_DONE", turn: TURN });
    expect(s).toEqual(COMPOSER_IDLE);
  });

  it("a server error event reoffers with the retained text", () => {
    let s = submitted();
    s = composerReducer(s, { type: "STREAM_DELTA", text: "x" });
    s = composerReducer(s, { type: "STREAM_ERROR", code: "model_timeout" });
    expect(s).toEqual({
      phase: "reoffer",
      draft: "how does it sit?",
      code: "model_timeout",
    });
  });

  it("connection loss moves to confirming, not reoffer", () => {
    let s = submitted();
    s = composerReducer(s, { type: "STREAM_DELTA", text: "x" });
    s = composerReducer(s, { type: "CONNECTION_LOST" });
    expect(s).toMatchObject({
      phase: "confirming",
      clientMsgId: "cmid-1",
      sentAt: T0,
      checks: 0,
    });
  });
});

describe("pre-stream failures", () => {
  it("budget rests the composer with the guest line", () => {
    const s = composerReducer(submitted(), {
      type: "PRE_STREAM_BUDGET",
      guestLine: "let's pick it up later",
      restedUntil: T0 + 60_000,
    });
    expect(s).toEqual({
      phase: "rested",
      guestLine: "let's pick it up later",
      restedUntil: T0 + 60_000,
    });
  });

  it("turn_in_flight blocks and keeps the draft", () => {
    const s = composerReducer(submitted(), {
      type: "PRE_STREAM_IN_FLIGHT",
      now: T0 + 10,
    });
    expect(s).toEqual({
      phase: "blocked",
      draft: "how does it sit?",
      since: T0 + 10,
    });
  });

  it("other pre-stream failures reoffer", () => {
    const s = composerReducer(submitted(), {
      type: "PRE_STREAM_FAILED",
      code: "upstream_error",
    });
    expect(s).toMatchObject({ phase: "reoffer", draft: "how does it sit?" });
  });
});

describe("confirming", () => {
  const confirming = composerReducer(submitted(), { type: "CONNECTION_LOST" });

  it("found commits and clears", () => {
    const s = composerReducer(confirming, { type: "CONFIRM_FOUND", turn: TURN });
    expect(s).toEqual(COMPOSER_IDLE);
  });

  it("not-found inside the window keeps confirming and counts checks", () => {
    const s = composerReducer(confirming, {
      type: "CONFIRM_NOT_FOUND",
      now: T0 + CONFIRM_WINDOW_MS - 1,
    });
    expect(s).toMatchObject({ phase: "confirming", checks: 1 });
  });

  it("not-found past the 150 s window reoffers the retained text", () => {
    const s = composerReducer(confirming, {
      type: "CONFIRM_NOT_FOUND",
      now: T0 + CONFIRM_WINDOW_MS + 1,
    });
    expect(s).toEqual({
      phase: "reoffer",
      draft: "how does it sit?",
      code: "connection_lost",
    });
  });

  it("ignores submits while confirming", () => {
    const s = composerReducer(confirming, {
      type: "SUBMIT",
      clientMsgId: "cmid-2",
      now: T0 + 5,
    });
    expect(s.phase).toBe("confirming");
  });
});

describe("reoffer", () => {
  const reoffer: ComposerState = {
    phase: "reoffer",
    draft: "how does it sit?",
    code: "model_error",
  };

  it("resends only on an explicit human SUBMIT, with a fresh id", () => {
    const s = composerReducer(reoffer, {
      type: "SUBMIT",
      clientMsgId: "cmid-fresh",
      now: T0 + 99,
    });
    expect(s).toEqual({
      phase: "submitting",
      draft: "how does it sit?",
      clientMsgId: "cmid-fresh",
      sentAt: T0 + 99,
    });
  });

  it("never auto-resends: stream/confirm events are inert", () => {
    expect(
      composerReducer(reoffer, { type: "STREAM_DELTA", text: "x" }),
    ).toEqual(reoffer);
    expect(
      composerReducer(reoffer, { type: "CONFIRM_NOT_FOUND", now: T0 }),
    ).toEqual(reoffer);
  });

  it("the retained text stays editable", () => {
    const s = composerReducer(reoffer, { type: "EDIT", draft: "edited" });
    expect(s).toEqual({ phase: "reoffer", draft: "edited", code: "model_error" });
  });
});

describe("rested", () => {
  const rested: ComposerState = {
    phase: "rested",
    guestLine: "later",
    restedUntil: T0 + 1000,
  };

  it("ignores submits and edits while resting", () => {
    expect(
      composerReducer(rested, { type: "SUBMIT", clientMsgId: "x", now: T0 }),
    ).toEqual(rested);
    expect(composerReducer(rested, { type: "EDIT", draft: "x" })).toEqual(rested);
  });

  it("wakes on REST_ELAPSED", () => {
    expect(composerReducer(rested, { type: "REST_ELAPSED" })).toEqual(
      COMPOSER_IDLE,
    );
  });
});

describe("blocked", () => {
  const blocked: ComposerState = {
    phase: "blocked",
    draft: "mine too",
    since: T0,
  };

  it("returns to idle with the draft intact when the other tab settles", () => {
    expect(composerReducer(blocked, { type: "OTHER_TAB_SETTLED" })).toEqual({
      phase: "idle",
      draft: "mine too",
    });
  });

  it("ignores submits while blocked", () => {
    expect(
      composerReducer(blocked, { type: "SUBMIT", clientMsgId: "x", now: T0 }),
    ).toEqual(blocked);
  });
});

describe("splitAtSentenceBoundary (reduced-motion flushing)", () => {
  it("flushes through the last boundary and buffers the tail", () => {
    expect(splitAtSentenceBoundary("One. Two. And a ta")).toEqual([
      "One. Two.",
      " And a ta",
    ]);
  });

  it("holds everything when no boundary exists yet", () => {
    expect(splitAtSentenceBoundary("no boundary he")).toEqual([
      "",
      "no boundary he",
    ]);
  });

  it("does not split mid-number (1.3 m stays whole)", () => {
    expect(splitAtSentenceBoundary("about 1.3 m apar")).toEqual([
      "",
      "about 1.3 m apar",
    ]);
  });

  it("question marks are boundaries", () => {
    expect(splitAtSentenceBoundary("Want more? I co")).toEqual([
      "Want more?",
      " I co",
    ]);
  });
});
