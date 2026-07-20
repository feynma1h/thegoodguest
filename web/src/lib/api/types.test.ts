/**
 * assembleScene is the seam between the backend contract and the viewer:
 * these tests pin that placed objects with signed URLs become
 * PositionedSplats verbatim, and that everything else is REPORTED as
 * unrenderable rather than silently dropped.
 */

import { describe, expect, it } from "vitest";

import { assembleScene, type SceneAssets } from "./types";

const GS = "gs://outputs/scenes/s1/splats/00_chair.ply";

function assets(overrides: Partial<SceneAssets["manifest"]> = {}): SceneAssets {
  return {
    scene_id: "s1",
    manifest: {
      scene_id: "s1",
      manifest_version: 2,
      objects: [
        {
          object_id: "obj_000",
          label: "chair",
          placed: true,
          method: "depth_fit",
          splat_gcs_uri: GS,
          world_transform: {
            position: [1, 0.5, -2],
            rotation_xyzw: [0, 0.383, 0, 0.924],
            scale: 1.4,
          },
        },
      ],
      ...overrides,
    },
    asset_urls: { [GS]: "https://signed.example/chair.ply" },
    expires_at: new Date().toISOString(),
  };
}

describe("assembleScene", () => {
  it("maps placed objects with signed URLs to PositionedSplats verbatim", () => {
    const { splats, unrenderable } = assembleScene(assets());
    expect(unrenderable).toEqual([]);
    expect(splats).toEqual([
      {
        url: "https://signed.example/chair.ply",
        label: "chair",
        position: [1, 0.5, -2],
        rotation_xyzw: [0, 0.383, 0, 0.924],
        scale: 1.4,
      },
    ]);
  });

  it("reports unplaced objects as unrenderable", () => {
    const a = assets({
      objects: [
        {
          object_id: "obj_000",
          label: "lamp",
          placed: false,
          method: null,
          reason: "insufficient_observations",
          splat_gcs_uri: GS,
          world_transform: null,
        },
      ],
    });
    const { splats, unrenderable } = assembleScene(a);
    expect(splats).toEqual([]);
    expect(unrenderable).toHaveLength(1);
    expect(unrenderable[0].reason).toBe("insufficient_observations");
  });

  it("reports placed objects whose splat URI has no signed URL", () => {
    const a = assets();
    a.asset_urls = {}; // signing omitted this object
    const { splats, unrenderable } = assembleScene(a);
    expect(splats).toEqual([]);
    expect(unrenderable).toHaveLength(1);
  });

  it("tolerates manifests without an objects array (pre-v2)", () => {
    const a = assets();
    delete a.manifest.objects;
    const { splats, unrenderable } = assembleScene(a);
    expect(splats).toEqual([]);
    expect(unrenderable).toEqual([]);
  });
});
