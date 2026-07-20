/**
 * LiveApiClient speaks api-public's exact HTTP contract; these tests pin
 * the request shape (paths, Bearer header) and the error mapping
 * ({error, detail} bodies -> ApiError, 409 scene_not_ready ->
 * SceneNotReadyError carrying the status).
 */

import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, LiveApiClient, SceneNotReadyError } from "./client";

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
