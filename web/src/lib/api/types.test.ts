/**
 * assembleScene is the seam between the backend contract and the viewer:
 * these tests pin that placed objects with signed URLs become
 * PositionedSplats verbatim, and that everything else is REPORTED as
 * unrenderable rather than silently dropped.
 */

import { describe, expect, it } from "vitest";

import {
  assembleScene,
  type SceneAssets,
  type ShellDocV2,
  type ShellDocV3,
  type ShellWallEntryV3,
} from "./types";

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

function shellDoc(overrides: Partial<ShellDocV2> = {}): ShellDocV2 {
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

  it("carries confidence null on every v2 plane (no source field)", () => {
    const a = assets();
    a.shell = shellDoc();
    const { shell } = assembleScene(a);
    expect(shell!.map((p) => p.confidence)).toEqual([null, null, null]);
  });
});

// ---------------------------------------------------------------------------
// Shell mapping, v3 polygon walls (decision 0077 — methods "roomplan" and
// "anchor_envelope")
// ---------------------------------------------------------------------------

/** A notched explicit-outline wall (the spike's wall_00 class): 6 corners,
 * interior-wound, facing +Z. */
const NOTCHED_WALL: [number, number, number][] = [
  [0, -1, 0],
  [4, -1, 0],
  [4, 1, 0],
  [2.5, 1, 0],
  [2.5, 0.4, 0],
  [0, 0.4, 0],
];

function v3Wall(overrides: Partial<ShellWallEntryV3> = {}): ShellWallEntryV3 {
  return {
    wall_id: "wall_01",
    polygon: [
      [0, -1, -2],
      [4, -1, -2],
      [4, 1, -2],
      [0, 1, -2],
    ],
    classification: "wall",
    confidence: "high",
    openings: [],
    provenance: { source: "roomplan" },
    material: material("painted", "#aab9c3"),
    ...overrides,
  };
}

function shellDocV3(overrides: Partial<ShellDocV3> = {}): ShellDocV3 {
  return {
    shell_version: 3,
    scene_id: "s1",
    status: "ready",
    reason: null,
    method: "roomplan",
    floor: {
      // 5-corner floor polygon — v3 floors ship verbatim CapturedRoom
      // outlines, not rectangles.
      polygon: [
        [0, -1, 2],
        [4, -1, 2],
        [4, -1, -2],
        [1, -1, -2],
        [0, -1, -1],
      ],
      y: -1,
      confidence: "high",
      provenance: { source: "roomplan" },
      material: material("stone", "#c8c1b7", 0.8),
    },
    walls: [
      v3Wall(),
      v3Wall({
        wall_id: "wall_00",
        polygon: NOTCHED_WALL,
        confidence: "medium",
        openings: [
          { classification: "opening", rect_uv: [[0, 0], [1, 0.63]] },
        ],
      }),
    ],
    quality: {},
    ...overrides,
  };
}

describe("assembleScene shell mapping (v3)", () => {
  it("maps a v3 roomplan shell: floor polygon first, then polygon walls verbatim", () => {
    const a = assets();
    const doc = shellDocV3();
    a.shell = doc;
    const { shell } = assembleScene(a);
    expect(shell!.map((p) => p.kind)).toEqual(["floor", "wall", "wall"]);
    expect(shell![0].corners).toEqual(doc.floor!.polygon);
    expect(shell![1].corners).toEqual(doc.walls[0].polygon);
    // The explicit-outline wall keeps all 6 corners — nothing is
    // rectangle-ified client-side.
    expect(shell![2].corners).toEqual(NOTCHED_WALL);
    expect(shell![1].material.albedo_hex).toBe("#aab9c3");
  });

  it("carries per-surface confidence through for treatments", () => {
    const a = assets();
    a.shell = shellDocV3();
    const { shell } = assembleScene(a);
    expect(shell!.map((p) => p.confidence)).toEqual(["high", "high", "medium"]);
  });

  it("carries v3 openings through, including through-openings", () => {
    const a = assets();
    a.shell = shellDocV3();
    const { shell } = assembleScene(a);
    expect(shell![2].openings).toEqual([
      { classification: "opening", rect_uv: [[0, 0], [1, 0.63]] },
    ]);
  });

  it("renders envelope walls from the polygon, never the measured quad", () => {
    const a = assets();
    const rendered: [number, number, number][] = [
      [0, -1.4, -2],
      [4, -1.4, -2],
      [4, 1.1, -2],
      [0, 1.1, -2],
    ];
    const measured: [number, number, number][] = [
      [0.4, -0.9, -2],
      [3.1, -0.9, -2],
      [3.1, 1.1, -2],
      [0.4, 1.1, -2],
    ];
    a.shell = shellDocV3({
      method: "anchor_envelope",
      floor: {
        polygon: [
          [0, -1.4, 2],
          [4, -1.4, 2],
          [4, -1.4, -2],
          [0, -1.4, -2],
        ],
        measured_polygon: null,
        y: -1.4,
        provenance: { source: "envelope_intersection" },
        material: material(null, "#bbb099"),
      },
      walls: [
        v3Wall({
          polygon: rendered,
          measured_quad: measured,
          confidence: null,
          provenance: { source: "anchor_envelope", merged_wall_id: "wall_05" },
        }),
      ],
    });
    const { shell } = assembleScene(a);
    expect(shell![1].corners).toEqual(rendered);
    expect(shell![1].confidence).toBeNull();
  });

  it("yields shell null for a v3 unavailable document", () => {
    const a = assets();
    a.shell = shellDocV3({
      status: "unavailable",
      reason: "no_geometry_source",
      method: "anchor_envelope",
      floor: null,
      walls: [],
    });
    expect(assembleScene(a).shell).toBeNull();
  });

  it("skips a degenerate v3 wall polygon, keeps its siblings", () => {
    const a = assets();
    a.shell = shellDocV3({
      walls: [
        v3Wall({ polygon: [[0, -1, -2], [4, -1, -2]] }),
        v3Wall({ wall_id: "wall_02" }),
      ],
    });
    const { shell } = assembleScene(a);
    expect(shell!.filter((p) => p.kind === "wall")).toHaveLength(1);
  });
});

describe("assembleScene splat clip (decision 0104)", () => {
  const clip = {
    kind: "roomplan_box",
    margin_m: 0.1,
    center_world: [1, 2, 3] as [number, number, number],
    half_extents_m: [0.6, 0.4, 1.2] as [number, number, number],
    yaw_rad: 0.5,
    removed_fraction: 0.31,
  };

  it("carries a declared clip volume through to the viewer", () => {
    const { splats } = assembleScene(assets({
      objects: [{ ...assets().manifest.objects![0], splat_clip: clip }],
    }));
    expect(splats).toHaveLength(1);
    expect(splats[0].clip).toEqual({
      center_world: [1, 2, 3],
      half_extents_m: [0.6, 0.4, 1.2],
      yaw_rad: 0.5,
    });
  });

  it("leaves clip undefined when the splat fits its box", () => {
    const { splats } = assembleScene(assets());
    expect(splats[0].clip).toBeUndefined();
  });

  it("ignores a clip of an unknown kind rather than guessing a volume", () => {
    const { splats } = assembleScene(assets({
      objects: [{
        ...assets().manifest.objects![0],
        splat_clip: { ...clip, kind: "something_else" },
      }],
    }));
    expect(splats[0].clip).toBeUndefined();
  });

  it("never lets a clip change the transform it accompanies", () => {
    const plain = assembleScene(assets()).splats[0];
    const clipped = assembleScene(assets({
      objects: [{ ...assets().manifest.objects![0], splat_clip: clip }],
    })).splats[0];
    expect(clipped.position).toEqual(plain.position);
    expect(clipped.rotation_xyzw).toEqual(plain.rotation_xyzw);
    expect(clipped.scale).toEqual(plain.scale);
  });
});

describe("assembleScene compressed tier (decision 0126)", () => {
  it("prefers the compressed URL when one exists for that splat", () => {
    const a = assets();
    a.asset_urls_compressed = { [GS]: "https://signed.example/chair.spz" };
    const { splats } = assembleScene(a);
    expect(splats).toHaveLength(1);
    expect(splats[0].url).toBe("https://signed.example/chair.spz");
  });

  it("falls back to the PLY when the map is absent", () => {
    const { splats } = assembleScene(assets());
    expect(splats[0].url).toBe("https://signed.example/chair.ply");
  });

  it("falls back to the PLY when the map exists but omits this splat", () => {
    const a = assets();
    a.asset_urls_compressed = { "gs://outputs/scenes/s1/splats/99_other.ply": "x" };
    const { splats } = assembleScene(a);
    expect(splats[0].url).toBe("https://signed.example/chair.ply");
  });

  it("changes nothing but the URL — transform, label and clip are untouched", () => {
    const plain = assembleScene(assets()).splats[0];
    const a = assets();
    a.asset_urls_compressed = { [GS]: "https://signed.example/chair.spz" };
    const comp = assembleScene(a).splats[0];
    expect({ ...comp, url: null }).toEqual({ ...plain, url: null });
  });

  it("renders from the compressed URL alone when only that one is present", () => {
    // api-public always signs the PLY too, so this shape should not occur in
    // production. It is pinned deliberately: a compressed URL points at a real
    // object the converter wrote, so the honest response is to render it
    // rather than to report the piece missing over a wire-format accident.
    const a = assets();
    a.asset_urls = {};
    a.asset_urls_compressed = { [GS]: "https://signed.example/chair.spz" };
    const { splats, unrenderable } = assembleScene(a);
    expect(splats).toHaveLength(1);
    expect(splats[0].url).toBe("https://signed.example/chair.spz");
    expect(unrenderable).toEqual([]);
  });
});
