/**
 * LiveApiClient speaks api-public's exact HTTP contract; these tests pin
 * the request shape (paths, Bearer header) and the error mapping
 * ({error, detail} bodies -> ApiError, 409 scene_not_ready ->
 * SceneNotReadyError carrying the status), and the room guide's calls:
 * its turn's SSE events, its buttons, and its pre-stream errors.
 */

import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  BudgetExhaustedError,
  LiveApiClient,
  parseGuideSseBlock,
  SceneNotReadyError,
  TurnInFlightError,
} from "./client";

const BASE = "https://api.example";

function mockFetch(status: number, body: unknown) {
  const fn = vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => vi.unstubAllGlobals());

describe("LiveApiClient", () => {
  it("sends the Bearer token and hits /scenes with the limit", async () => {
    const fetchFn = mockFetch(200, { scenes: [] });
    const client = new LiveApiClient(BASE, async () => "tok-123");
    await client.listScenes(7);
    expect(fetchFn).toHaveBeenCalledWith(`${BASE}/scenes?limit=7`, {
      headers: { Authorization: "Bearer tok-123" },
    });
  });

  it("unwraps the scenes envelope", async () => {
    const scene = { scene_id: "s1", status: "ready" };
    mockFetch(200, { scenes: [scene] });
    const client = new LiveApiClient(BASE, async () => "t");
    expect(await client.listScenes()).toEqual([scene]);
  });

  it("maps error bodies to ApiError with status and code", async () => {
    mockFetch(403, { error: "forbidden", detail: "not yours" });
    const client = new LiveApiClient(BASE, async () => "t");
    const err = await client.getSceneByBundle("b1").catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(403);
    expect(err.code).toBe("forbidden");
  });

  it("maps 409 scene_not_ready to SceneNotReadyError with the status", async () => {
    mockFetch(409, { error: "scene_not_ready", status: "processing" });
    const client = new LiveApiClient(BASE, async () => "t");
    const err = await client.getSceneAssets("s1").catch((e) => e);
    expect(err).toBeInstanceOf(SceneNotReadyError);
    expect(err.sceneStatus).toBe("processing");
  });

  it("fails fast without a token instead of sending an unauthed request", async () => {
    const fetchFn = mockFetch(200, {});
    const client = new LiveApiClient(BASE, async () => null);
    const err = await client.listScenes().catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.code).toBe("no_local_token");
    expect(fetchFn).not.toHaveBeenCalled();
  });
});

describe("the room guide's calls (decision 0376)", () => {
  const stream = (blocks: string[]) =>
    new ReadableStream<Uint8Array>({
      start(controller) {
        const enc = new TextEncoder();
        for (const b of blocks) controller.enqueue(enc.encode(b));
        controller.close();
      },
    });
  const state = { poses: {}, can_undo: false, cards: {} };

  it("parses every event a turn streams", () => {
    expect(parseGuideSseBlock('event: delta\ndata: {"text": "Hi"}')).toEqual({ type: "delta", text: "Hi" });
    expect(parseGuideSseBlock('event: note\ndata: {"text": "Looking…"}')).toEqual({ type: "note", text: "Looking…" });
    expect(parseGuideSseBlock('event: card\ndata: {"id": "p1", "words": ["w"], "status": "ready"}')).toEqual({
      type: "card", card: { id: "p1", words: ["w"], status: "ready" },
    });
    expect(parseGuideSseBlock(`event: play\ndata: {"plan": null, "state": ${JSON.stringify(state)}}`)).toEqual({
      type: "play", plan: null, state,
    });
    expect(parseGuideSseBlock('event: focus\ndata: {"pieces": ["desk"], "zones": []}')).toEqual({
      type: "focus", focus: { pieces: ["desk"], zones: [] },
    });
    expect(
      parseGuideSseBlock(`event: done\ndata: {"turn": {"turn_index": 2, "client_msg_id": "c"}, "state": ${JSON.stringify(state)}}`),
    ).toEqual({ type: "done", turnIndex: 2, clientMsgId: "c", state });
    expect(parseGuideSseBlock('event: error\ndata: {"code": "model_timeout"}')).toEqual({ type: "error", code: "model_timeout" });
    expect(parseGuideSseBlock(": ping")).toBeNull();
    expect(parseGuideSseBlock('event: something_new\ndata: {}')).toBeNull();
  });

  it("posts a turn and reads its stream to the end", async () => {
    const fetchFn = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      body: stream([
        'event: delta\ndata: {"text": "The desk"}\n\n: ping\n\n',
        'event: delta\ndata: {"text": " faces the wall."}\n\nevent: done\ndata: {"turn": {"turn_index": 0, "client_msg_id": "c1"}, "state": {"poses": {}, "can_undo": false, "cards": {}}}\n\n',
      ]),
    });
    vi.stubGlobal("fetch", fetchFn);
    const client = new LiveApiClient(BASE, async () => "t");
    const events = [];
    for await (const ev of await client.sendGuideTurn("s1", { opening: true }, "c1")) events.push(ev);
    expect(events.map((e) => e.type)).toEqual(["delta", "delta", "done"]);
    const [url, init] = fetchFn.mock.calls[0];
    expect(url).toBe(`${BASE}/scenes/s1/guide/turns`);
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({ client_msg_id: "c1", text: "", opening: true });
    expect(init.headers.Authorization).toBe("Bearer t");
  });

  it("says a stream that ends without its last word was lost", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true, status: 200, body: stream(['event: delta\ndata: {"text": "The"}\n\n']),
    }));
    const client = new LiveApiClient(BASE, async () => "t");
    const events = [];
    for await (const ev of await client.sendGuideTurn("s1", { text: "hi" }, "c2")) events.push(ev);
    expect(events.at(-1)).toEqual({ type: "error", code: "connection_lost" });
  });

  it("throws the guest's pre-stream errors before any stream exists", async () => {
    mockFetch(429, { error: "budget_exhausted", guest_line: "Later.", resets_at: "2026-11-13T00:00:00+00:00" });
    const client = new LiveApiClient(BASE, async () => "t");
    const rested = await client.sendGuideTurn("s1", { text: "hi" }, "c").catch((e) => e);
    expect(rested).toBeInstanceOf(BudgetExhaustedError);
    expect(rested.guestLine).toBe("Later.");
    mockFetch(409, { error: "turn_in_flight" });
    expect(await client.sendGuideTurn("s1", { text: "hi" }, "c").catch((e) => e)).toBeInstanceOf(TurnInFlightError);
  });

  it("shows a card and puts it back through their own routes", async () => {
    const move = { plan: null, state };
    const fetchFn = mockFetch(200, move);
    const client = new LiveApiClient(BASE, async () => "t");
    expect(await client.showGuideCard("s1", "p1")).toEqual(move);
    expect(fetchFn.mock.calls[0][0]).toBe(`${BASE}/scenes/s1/guide/show`);
    expect(JSON.parse(fetchFn.mock.calls[0][1].body)).toEqual({ proposal_id: "p1" });
    await client.undoGuide("s1");
    expect(fetchFn.mock.calls[1][0]).toBe(`${BASE}/scenes/s1/guide/undo`);
    mockFetch(409, { error: "proposal_stale" });
    const stale = await client.showGuideCard("s1", "p1").catch((e) => e);
    expect(stale).toBeInstanceOf(ApiError);
    expect(stale.code).toBe("proposal_stale");
  });
});
