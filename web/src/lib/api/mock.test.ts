/**
 * The mock fixtures are the offline UI's data source; these tests pin
 * that every SceneStatus is reachable, that the ready scene's assets
 * assemble into renderable splats, and that the mock honors the same
 * error contract as the live client.
 */

import { describe, expect, it } from "vitest";

import { MockApiClient, MOCK_READY_SCENE_ID } from "./mock";
import { SceneNotReadyError } from "./client";
import { assembleScene, SCENE_STATUSES } from "./types";

describe("MockApiClient", () => {
  it("covers every SceneStatus exactly once", async () => {
    const scenes = await new MockApiClient().listScenes();
    expect(scenes.map((s) => s.status).sort()).toEqual([...SCENE_STATUSES].sort());
  });

  it("lists newest first", async () => {
    const scenes = await new MockApiClient().listScenes();
    const times = scenes.map((s) => s.created_at);
    expect(times).toEqual([...times].sort().reverse());
  });

  it("ready scene assets assemble into positioned splats", async () => {
    const assets = await new MockApiClient().getSceneAssets(MOCK_READY_SCENE_ID);
    const { splats, unrenderable } = assembleScene(assets);
    expect(splats.length).toBeGreaterThanOrEqual(3);
    for (const s of splats) {
      expect(s.url.startsWith("/dev-fixtures/")).toBe(true);
      expect(s.scale).toBeGreaterThan(0);
    }
    // The fixture deliberately includes one unplaced object so the UI's
    // "not shown" path is reachable offline.
    expect(unrenderable.length).toBe(1);
  });

  it("non-ready scenes raise SceneNotReadyError from getSceneAssets", async () => {
    const client = new MockApiClient();
    const processing = client.scenes.find((s) => s.status === "processing")!;
    const err = await client.getSceneAssets(processing.scene_id).catch((e) => e);
    expect(err).toBeInstanceOf(SceneNotReadyError);
    expect(err.sceneStatus).toBe("processing");
  });

  it("getSceneByBundle resolves each fixture's bundle_id", async () => {
    const client = new MockApiClient();
    for (const scene of client.scenes) {
      const found = await client.getSceneByBundle(scene.bundle_id!);
      expect(found.scene_id).toBe(scene.scene_id);
    }
  });
});
