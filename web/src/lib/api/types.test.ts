/**
 * assembleScene is the seam between the backend contract and the viewer:
 * these tests pin that placed objects with signed URLs become
 * PositionedSplats verbatim, and that everything else is REPORTED as
 * unrenderable rather than silently dropped.
 */

import { describe, expect, it } from "vitest";

import { assembleScene, type SceneAssets, type ShellDoc } from "./types";

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

// ---------------------------------------------------------------------------
// Shell mapping (decision 0066)
// ---------------------------------------------------------------------------

const FLOOR_TEX = "gs://outputs/scenes/s1/shell/textures/floor.png";
const WALL_TEX = "gs://outputs/scenes/s1/shell/textures/wall_00.png";

function shellDoc(overrides: Partial<ShellDoc> = {}): ShellDoc {
  return {
    shell_version: 1,
    scene_id: "s1",
    status: "ready",
    reason: null,
    method: "arkit_planes",
    floor: {
      quad: [
        [0, -1, 2],
        [4, -1, 2],
        [4, -1, -2],
        [0, -1, -2],
      ],
      y: -1,
      texture_gcs_uri: FLOOR_TEX,
      observed_fraction: 0.8,
      inpainted_fraction: 0.1,
      source: "baked",
    },
    walls: [
      {
        wall_id: "wall_00",
        quad: [
          [0, -1, -2],
          [4, -1, -2],
          [4, 1, -2],
          [0, 1, -2],
        ],
        texture_gcs_uri: WALL_TEX,
        observed_fraction: 0.7,
        inpainted_fraction: 0.2,
        source: "baked",
        classification: "wall",
      },
      {
        wall_id: "wall_01",
        quad: [
          [0, -1, 2],
          [0, -1, -2],
          [0, 1, -2],
          [0, 1, 2],
        ],
        texture_gcs_uri: null,
        observed_fraction: 0.05,
        inpainted_fraction: 0,
        source: "unobserved",
        classification: null,
      },
    ],
    quality: { planes_in_bundle: 3, frames_used: 4 },
    ...overrides,
  };
}

describe("assembleScene shell mapping", () => {
  it("yields shell null when the field is absent (not yet)", () => {
    const { shell } = assembleScene(assets());
    expect(shell).toBeNull();
  });

  it("yields shell null when the field is explicitly null", () => {
    const a = assets();
    a.shell = null;
    expect(assembleScene(a).shell).toBeNull();
  });

  it("yields shell null for an unavailable document (never coming)", () => {
    const a = assets();
    a.shell = shellDoc({ status: "unavailable", reason: "no_geometry_source", floor: null, walls: [] });
    expect(assembleScene(a).shell).toBeNull();
    // The raw distinction stays readable on the assets object itself.
    expect(a.shell.status).toBe("unavailable");
  });

  it("maps a ready shell to planes: floor first, signed texture URLs", () => {
    const a = assets();
    a.shell = shellDoc();
    a.asset_urls[FLOOR_TEX] = "https://signed.example/floor.png";
    a.asset_urls[WALL_TEX] = "https://signed.example/wall_00.png";
    const { shell } = assembleScene(a);
    expect(shell).not.toBeNull();
    expect(shell!.map((p) => p.kind)).toEqual(["floor", "wall", "wall"]);
    expect(shell![0].texture_url).toBe("https://signed.example/floor.png");
    expect(shell![0].corners).toEqual(shellDoc().floor!.quad);
    expect(shell![1].texture_url).toBe("https://signed.example/wall_00.png");
    expect(shell![0].observed_fraction).toBe(0.8);
    expect(shell![0].inpainted_fraction).toBe(0.1);
  });

  it("maps untextured (unobserved) planes with texture_url null", () => {
    const a = assets();
    a.shell = shellDoc();
    a.asset_urls[FLOOR_TEX] = "https://signed.example/floor.png";
    a.asset_urls[WALL_TEX] = "https://signed.example/wall_00.png";
    const { shell } = assembleScene(a);
    expect(shell![2].texture_url).toBeNull();
  });

  it("maps a textured plane whose URL was not signed to texture_url null", () => {
    const a = assets();
    a.shell = shellDoc();
    // No asset_urls entries for the shell textures at all.
    const { shell } = assembleScene(a);
    expect(shell![0].texture_url).toBeNull();
  });

  it("yields shell null for a ready doc with no planes at all", () => {
    const a = assets();
    a.shell = shellDoc({ floor: null, walls: [] });
    expect(assembleScene(a).shell).toBeNull();
  });

  it("handles a walls-only shell (open dollhouse ships as detected)", () => {
    const a = assets();
    const doc = shellDoc({ floor: null });
    a.shell = doc;
    const { shell } = assembleScene(a);
    expect(shell!.map((p) => p.kind)).toEqual(["wall", "wall"]);
  });
});
