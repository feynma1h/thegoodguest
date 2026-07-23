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
// Shell mapping (decisions 0066/0069 — shell.json v2)
// ---------------------------------------------------------------------------

function material(
  family: string | null,
  albedo: string | null,
  roughness = 0.85,
) {
  return {
    family,
    family_confidence: family ? 0.8 : null,
    albedo_hex: albedo,
    secondary_hex: null,
    params: {},
    render: { roughness },
    source: { observed_fraction: 0.5, texel_count: 800, frames_used: 3 },
    inference: {
      model: family ? "claude-sonnet-5" : null,
      material_version: 1,
    },
  };
}

const FLOOR_POLYGON: [number, number, number][] = [
  [0, -1, 2],
  [4, -1, 2],
  [4, -1, -2],
  [0, -1, -2],
];

function shellDoc(overrides: Partial<ShellDoc> = {}): ShellDoc {
  return {
    shell_version: 2,
    scene_id: "s1",
    status: "ready",
    reason: null,
    method: "arkit_planes",
    floor: {
      polygon: FLOOR_POLYGON,
      measured_polygon: FLOOR_POLYGON,
      y: -1,
      provenance: { edges: ["observed", "observed", "observed", "observed"] },
      material: material("wood", "#8a6f52", 0.6),
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
        measured_quad: [
          [0, -0.7, -2],
          [4, -0.7, -2],
          [4, 1, -2],
          [0, 1, -2],
        ],
        edges: {
          bottom: { state: "extended_to_floor", extension_m: 0.3 },
          top: { state: "observed", extension_m: 0 },
          left: { state: "observed", extension_m: 0 },
          right: { state: "observed", extension_m: 0 },
        },
        openings: [
          { classification: "door", rect_uv: [[0.2, 0], [0.4, 0.9]] },
        ],
        classification: "wall",
        material: material("painted", "#c9b9a4"),
      },
      {
        wall_id: "wall_01",
        quad: [
          [0, -1, 2],
          [0, -1, -2],
          [0, 1, -2],
          [0, 1, 2],
        ],
        measured_quad: [
          [0, -1, 2],
          [0, -1, -2],
          [0, 1, -2],
          [0, 1, 2],
        ],
        edges: {
          bottom: { state: "observed", extension_m: 0 },
          top: { state: "observed", extension_m: 0 },
          left: { state: "observed", extension_m: 0 },
          right: { state: "observed", extension_m: 0 },
        },
        openings: [],
        classification: null,
        material: material(null, null, 0.9),
      },
    ],
    quality: { planes_in_bundle: 3, frames_used: 4, material_version: 1 },
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

  it("maps a ready shell: floor polygon first, then wall quads, with materials", () => {
    const a = assets();
    a.shell = shellDoc();
    const { shell } = assembleScene(a);
    expect(shell).not.toBeNull();
    expect(shell!.map((p) => p.kind)).toEqual(["floor", "wall", "wall"]);
    // The floor's corners ARE the rendered polygon (not a quad).
    expect(shell![0].corners).toEqual(FLOOR_POLYGON);
    expect(shell![0].material).toEqual({
      albedo_hex: "#8a6f52",
      roughness: 0.6,
      family: "wood",
    });
    expect(shell![1].material.albedo_hex).toBe("#c9b9a4");
    // Nothing fetchable exists on the renderer contract (0069).
    expect("texture_url" in shell![0]).toBe(false);
  });

  it("carries wall openings through; the floor always has none", () => {
    const a = assets();
    a.shell = shellDoc();
    const { shell } = assembleScene(a);
    expect(shell![0].openings).toEqual([]);
    expect(shell![1].openings).toEqual([
      { classification: "door", rect_uv: [[0.2, 0], [0.4, 0.9]] },
    ]);
    expect(shell![2].openings).toEqual([]);
  });

  it("maps an unobserved plane to the null-albedo neutral treatment", () => {
    const a = assets();
    a.shell = shellDoc();
    const { shell } = assembleScene(a);
    expect(shell![2].material.albedo_hex).toBeNull();
    expect(shell![2].material.family).toBeNull();
    expect(shell![2].material.roughness).toBe(0.9);
  });

  it("yields shell null for a ready doc with no planes at all", () => {
    const a = assets();
    a.shell = shellDoc({ floor: null, walls: [] });
    expect(assembleScene(a).shell).toBeNull();
  });

  it("skips a degenerate floor polygon (fewer than 3 vertices)", () => {
    const a = assets();
    const doc = shellDoc();
    doc.floor = { ...doc.floor!, polygon: [[0, -1, 0], [1, -1, 0]] };
    a.shell = doc;
    const { shell } = assembleScene(a);
    expect(shell!.map((p) => p.kind)).toEqual(["wall", "wall"]);
  });

  it("handles a walls-only shell (open dollhouse ships as detected)", () => {
    const a = assets();
    const doc = shellDoc({ floor: null });
    a.shell = doc;
    const { shell } = assembleScene(a);
    expect(shell!.map((p) => p.kind)).toEqual(["wall", "wall"]);
  });
});
