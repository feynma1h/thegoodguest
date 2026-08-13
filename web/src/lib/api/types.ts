/**
 * Client-side mirror of api-public's read contract and the perception
 * manifest (manifest_version 2).
 *
 * Sources of truth (keep in sync):
 *   - services/api-public/public_server.py — SceneSummary shape (decision
 *     0019 fields), /scenes list envelope, /scenes/{id}/assets envelope.
 *   - services/perception-obj/process_receiver.py docstring — manifest v2.
 *   - services/perception-obj/fusion.py — fused object entries.
 *
 * Also defines PositionedSplat — the renderer-agnostic input contract for
 * SplatViewer — and the pure mapping from a SceneAssets response to it.
 */

export const SCENE_STATUSES = [
  "queued",
  "processing",
  "ready",
  "failed",
  "failed_incomplete",
  "failed_invalid",
] as const;

export type SceneStatus = (typeof SCENE_STATUSES)[number];

/** One scene as returned by GET /scenes and GET /scenes/by-bundle/{id}. */
export interface SceneSummary {
  scene_id: string;
  bundle_id: string | null;
  status: SceneStatus;
  result_uri: string | null;
  missing_paths: string[] | null;
  created_at: string; // ISO 8601
  updated_at: string; // ISO 8601
}

export interface WorldTransform {
  position: [number, number, number]; // meters, ARKit world frame (+Y up)
  rotation_xyzw: [number, number, number, number]; // unit quaternion
  /** Uniform (the shipped server contract) or per-axis — the latter only
   * from staged A/B fixtures; see PositionedSplat.scale. */
  scale: number | [number, number, number];
}

/** One fused physical object from the manifest's scene-level array. */
export interface FusedObject {
  object_id: string;
  label: string;
  placed: boolean;
  method:
    | "depth_fit" // fusion.py: LiDAR depth-cloud fit
    | "layout_triangulated" // fusion.py: multi-view ray triangulation
    | "roomplan_box" // box_placement.py: anchored to a measured RoomPlan box
    | "single_view_floor_contact" // contact_priors.py: dropped onto the floor
    | "single_view_wall_contact" // contact_priors.py: onto the nearest wall
    | null;
  reason?: string; // present when placed is false
  splat_gcs_uri: string | null;
  world_transform: WorldTransform | null;
  /** Present only when the splat overshoots its measured box (0104). */
  splat_clip?: {
    kind: string;
    margin_m: number;
    center_world: [number, number, number];
    half_extents_m: [number, number, number];
    yaw_rad: number;
    removed_fraction: number;
  } | null;
  quality?: Record<string, number | string | null>;
}

/** Top-level perception manifest (manifest_version 2). */
export interface SceneManifest {
  scene_id: string;
  manifest_version?: number;
  frame_count?: number;
  objects?: FusedObject[];
  frames?: unknown[];
}

/**
 * One plane's material {} as shell.json v2 carries it (decision 0069):
 * parametric, inferred from observed pixels — no raster textures exist
 * anywhere in the shell contract.
 */
export interface ShellMaterialEntry {
  family: string | null; // null = below gate / failed / no key -> clean neutral
  family_confidence: number | null;
  albedo_hex: string | null; // null = unobserved plane -> neutral treatment
  secondary_hex: string | null;
  params: { plank_direction_deg?: number };
  render: { roughness: number };
  source: { observed_fraction: number; texel_count: number; frames_used: number };
  inference: { model: string | null; material_version: number };
}

export interface ShellOpeningEntry {
  classification: string; // "door" | "window" | "opening" (v3 adds through-openings)
  /** [[u0,v0],[u1,v1]] normalized on the wall's rendered UV frame (v2: the
   * quad from corner 0; v3: the polygon's bounding rect in-plane). */
  rect_uv: [[number, number], [number, number]];
}

export interface ShellEdgeState {
  state: string; // "observed" | "extended_to_floor" | "extended_to_common_height" | "extended_to_wall:<id>"
  extension_m: number;
}

/**
 * One wall entry (shell.json v2, decision 0069). quad is the RENDERED
 * (closure-extended) geometry the viewer draws; measured_quad is the
 * DETECTED extent — what the AI layer may read; closure never mutates it.
 * Corners are wound so the front face points into the room; corner 0 is
 * the plane-frame origin (+U to corner 1, +V to corner 3).
 */
export interface ShellWallEntry {
  wall_id: string;
  quad: [number, number, number][]; // 4 rendered corners, meters
  measured_quad: [number, number, number][]; // 4 detected corners
  edges: Record<string, ShellEdgeState>; // bottom / top / left / right
  openings: ShellOpeningEntry[];
  classification: string | null; // ARKit verbatim (majority, non-opening)
  material: ShellMaterialEntry;
}

/** The floor entry (shell.json v2): an explicit polygon, not a quad. */
export interface ShellFloorEntry {
  polygon: [number, number, number][]; // rendered, N>=3, CCW in XZ
  measured_polygon: [number, number, number][]; // detected boundary
  y: number;
  provenance: { edges: string[] }; // per rendered segment
  material: ShellMaterialEntry;
}

/**
 * One wall entry (shell.json v3, decision 0077). Walls are POLYGONS —
 * interior-wound, verbatim geometry: method "roomplan" ships CapturedRoom
 * vertices (rect-from-dimensions 4-corner walls dominate; explicit
 * outlines carry more), method "anchor_envelope" ships the derived
 * envelope quads with the DETECTED extent beside them (measured_quad).
 * Corner 0 is NOT guaranteed to be the UV origin — winding normalization
 * may rotate the start; openings' rect_uv normalize on the polygon's
 * bounding rect in-plane (lib/shell3d.ts mirrors the server frame).
 */
export interface ShellWallEntryV3 {
  wall_id: string;
  polygon: [number, number, number][]; // N>=3, interior-fronting winding
  measured_quad?: [number, number, number][]; // anchor_envelope only
  // roomplan only, and only on a wall the server co-planarized with its
  // neighbours (decision 0082's kink fix): the CapturedRoom polygon as
  // MEASURED, beside the rendered one, which is projected onto the
  // group's mean plane. provenance.coplanarized_with names the group.
  // Same honesty invariant as measured_quad — never a substitute for
  // `polygon`, which is always what renders.
  measured_polygon?: [number, number, number][];
  classification: string | null;
  confidence: string | null; // "high" | "medium" | "low" (roomplan); null (envelope)
  openings: ShellOpeningEntry[];
  provenance: Record<string, unknown>; // {source: "roomplan" | "anchor_envelope" | "detected_extent", ...}
  material: ShellMaterialEntry;
}

/** The floor entry (shell.json v3): rendered polygon verbatim; the
 * envelope method carries the measured coverage polygon beside it. */
export interface ShellFloorEntryV3 {
  polygon: [number, number, number][]; // rendered, N>=3, CCW in XZ
  measured_polygon?: [number, number, number][] | null; // anchor_envelope only
  y: number;
  confidence?: string; // roomplan only ("high" | "medium" | "low")
  provenance: { source: string }; // "roomplan" | "envelope_intersection" | "detected_extent"
  material: ShellMaterialEntry;
}

interface ShellDocBase {
  scene_id: string;
  status: "ready" | "unavailable";
  reason: string | null; // "no_geometry_source" | "capture_expired" | null
  quality?: Record<string, unknown>;
}

/** The v2 closure shell (decision 0069) — the ARKIT_ONLY legacy shape. */
export interface ShellDocV2 extends ShellDocBase {
  shell_version: 2;
  method: "arkit_planes";
  floor: ShellFloorEntry | null;
  walls: ShellWallEntry[];
}

/** The v3 polygon-wall shell (decision 0077): CapturedRoom geometry
 * verbatim ("roomplan") or the LiDAR degrade envelope ("anchor_envelope"). */
export interface ShellDocV3 extends ShellDocBase {
  shell_version: 3;
  method: "roomplan" | "anchor_envelope";
  floor: ShellFloorEntryV3 | null;
  walls: ShellWallEntryV3[];
}

/**
 * The room shell document, verbatim from the assets response's sibling
 * `shell` field. The distinction the room page relies on: the FIELD being
 * null/absent = the shell stage hasn't landed yet (brief grace window);
 * a document with status "unavailable" = never coming (keep the grid).
 */
export type ShellDoc = ShellDocV2 | ShellDocV3;

/** GET /scenes/{scene_id}/assets response. */
export interface SceneAssets {
  scene_id: string;
  manifest: SceneManifest;
  /** Room shell sibling (decision 0066). Absent/null = not yet. */
  shell?: ShellDoc | null;
  asset_urls: Record<string, string>; // gs:// URI -> signed HTTPS URL
  /** The compressed tier (decision 0126), keyed by the SAME gs:// URI as
   * `asset_urls` so a lookup picks a format rather than an object. Present
   * only for splats that have been transcoded; absent map = tier not built
   * for this scene, which is a normal state, not an error. */
  asset_urls_compressed?: Record<string, string>;
  expires_at: string; // ISO 8601
}

/**
 * Conversation stage 1 (decision 0058). One completed turn as the wire
 * carries it — the server's client projection; internal fields (usage,
 * model, versions) never appear here.
 */
/**
 * What DELETE /account removed (decision 0095). Counts only — the server
 * deliberately ships no ids or object paths. `deleted: false` means the pass
 * was partial and calling again resumes it; the identity survives until a
 * pass completes, so the user can always retry.
 */
export interface AccountDeletionResult {
  deleted: boolean;
  identityDeleted: boolean;
  counts: {
    rooms: number;
    conversations: number;
    conversationMessages: number;
    uploadSessions: number;
    files: number;
  };
}

export interface ConversationTurn {
  turn_index: number;
  client_msg_id: string;
  user_text: string;
  assistant_text: string;
  created_at: string; // ISO 8601
}

export interface ConversationMeta {
  scene_id: string;
  turn_count: number;
  rested_until: string | null; // ISO 8601; set while the daily quota rests
}

/** GET /scenes/{scene_id}/conversation response. */
export interface ConversationSnapshot {
  conversation: ConversationMeta;
  turns: ConversationTurn[]; // ascending, last <=50
  cursor: { before: number } | null; // pagination handle; v1 may ignore
}

/**
 * The normalized guest-event stream — the seam both transports speak
 * (the PositionedSplat trick applied to conversation): LiveApiClient
 * parses SSE into these; MockApiClient yields them directly; components
 * cannot tell the transports apart.
 *
 * "connection_lost" is client-vocabulary for a stream that died without
 * a terminal event — the turn's fate is unknown and the composer
 * confirms by refetching with its client_msg_id.
 */
export type GuestEvent =
  | { type: "delta"; text: string }
  /** The room changed: refetch the design spec (decision 0131). Carries no
   * payload on purpose — the client stays a reader of the spec document
   * rather than a second place scene state is assembled. */
  | { type: "arrangement" }
  | { type: "done"; turn: ConversationTurn }
  | { type: "error"; code: string };

/**
 * Renderer-agnostic viewer input: a splat file plus its world transform.
 * SplatViewer consumes ONLY this shape — nothing about the API or Spark
 * leaks across that boundary in either direction.
 */
export interface PositionedSplat {
  url: string;
  label: string;
  position: [number, number, number];
  rotation_xyzw: [number, number, number, number];
  /**
   * Uniform splat-local -> world scale (the shipped v1 contract), or a
   * per-axis [x, y, z] scale — the uniform-vs-stretch comparison side, fed
   * only by staged fixtures today. Decision 0077 defers the per-axis knob
   * server-side; if it ever ships, this union is its landing shape.
   */
  scale: number | [number, number, number];
  /**
   * Optional clip volume (decision 0104): an oriented box, in world
   * coordinates, outside which this splat's points are not rendered.
   *
   * Box-anchored objects take their position and extent from a RoomPlan
   * box the operator verified 9/9, but their appearance from a splat
   * reconstructed off one view — so a mis-proportioned splat can reach
   * well past the measurement it is dressed in. The 0085 walk found a bed
   * overhanging its own footprint by 0.44 m, into the table and the chair,
   * in two independent rooms. That mass is known-false, and the server
   * declines to render it rather than moving or rescaling the object to
   * hide it.
   *
   * Optional by design: a renderer that ignores this draws exactly what it
   * drew before.
   */
  clip?: SplatClip;
  /**
   * Withheld from the room by a design proposal (action "remove",
   * decision 0131). The splat stays in this list on purpose: unmounting a
   * mesh is a full re-download and re-parse (0130 measured it), and
   * "back to measured" must always be one cheap action (0133). So a
   * removal is a HIDE, and undoing one costs nothing.
   */
  hidden?: boolean;
}

/** An oriented world-space box; yaw-only, matching RoomPlan boxes. */
export interface SplatClip {
  center_world: [number, number, number];
  half_extents_m: [number, number, number];
  yaw_rad: number;
}

/**
 * Renderer-agnostic shell plane (the PositionedSplat trick applied to the
 * shell, v2 per decision 0069): world geometry plus parametric material —
 * nothing fetchable, nothing renderer-shaped. SplatViewer consumes ONLY
 * this shape (decision 0053's containment rule).
 */
export interface ShellPlane {
  kind: "floor" | "wall";
  /** Walls: the rendered polygon, front face toward the room (v2 quads are
   * 4 corners with corner 0 the plane origin; v3 polygons may carry any
   * vertex count and any start corner — lib/shell3d.ts derives the frame).
   * Floor: the rendered polygon (N>=3, CCW in the XZ plane). */
  corners: [number, number, number][];
  material: {
    /** Measured dominant color; null = unobserved -> neutral treatment,
     * never a fake color. */
    albedo_hex: string | null;
    roughness: number;
    /** Confidence-gated family (null = clean matte); enables family-typed
     * micro-treatment later. */
    family: string | null;
  };
  /** Door/window/opening sub-regions in the wall's normalized UV frame
   * (walls only; always [] for the floor). */
  openings: ShellOpeningEntry[];
  /** Per-surface RoomPlan confidence ("high" | "medium" | "low"), carried
   * for treatments; null where the source has none (v2, envelope walls). */
  confidence: string | null;
}

/**
 * The Design Specification (decision 0131): a proposal sitting BESIDE the
 * measurement, never over it. A sibling of the manifest, like the shell —
 * every object it does not name is exactly where perception measured it.
 *
 * The invariant, and it is the whole reason this shape exists: every entry
 * carries `measured_transform` beside `proposed_transform`. The proposal is
 * renderable and the truth is one field away, in the same object, at every
 * layer. That makes the lie structurally unavailable rather than prohibited
 * by discipline — the house pattern from `measured_quad` (0069) and the
 * declared clip volume (0104).
 */
export interface SpecTransform {
  position: [number, number, number];
  rotation_xyzw: [number, number, number, number];
  scale: number;
}

/** The measured box's floor rectangle — what the outline draws. Server-sent
 * because the client cannot derive it: `PositionedSplat` carries no box and
 * `splat_clip` exists only where a splat overshoots. */
export interface SpecFootprint {
  center_world: [number, number, number];
  half_extents_m: [number, number, number];
  yaw_rad: number;
}

/** Why the piece is where it is — produced by the solver, never the model
 * (decision 0055 lists the reasoning trace as durable architecture). Absent
 * on a `remove`, which needs no geometry. */
export interface SpecSolverTrace {
  relation: string;
  anchor_resolved_to: string;
  constraints_applied: string[];
  reasoning: string;
}

export interface SpecEntry {
  key: string;
  action: "move" | "remove" | "turn";
  label: string;
  measured_transform: SpecTransform;
  proposed_transform: SpecTransform | null; // null for "remove"
  measured_footprint: SpecFootprint | null;
  solver: SpecSolverTrace | null;
  description: string;
  origin: { turn_index: number | null; client_msg_id: string | null };
  /** Whether the person corrected which way round this piece sits. Rides
   * independently of `action`, because a piece can be both moved and turned. */
  facing_flipped: boolean;
  /** WHAT THIS ENTRY OVERRULED (decision 0157), computed server-side so there
   * is one implementation of the rule.
   *
   * `measurement` — perception measured the piece here and the person asked to
   * see it elsewhere. The measurement stays on screen as its outline.
   *
   * `unresolved_default` — perception could not read which way round the piece
   * sits and shipped a fixed convention, so the value the person overruled was
   * never a measurement. There is no outline to draw: a half turn maps a
   * rectangle onto itself, so the measured footprint is exactly where the
   * piece already stands.
   *
   * Required rather than optional on purpose: an absent value would fall back
   * to drawing an outline, which is the wrong answer, and every construction
   * site has to say which kind of entry it is building. */
  departs_from: "measurement" | "unresolved_default";
  /** The key no longer resolves in the current manifest — a re-drive dropped
   * the object. Reported, never silently dropped and NEVER re-pointed: a spec
   * aimed at the wrong object would move the wrong furniture and nothing in
   * the system would notice. */
  orphaned: boolean;
}

/** GET /scenes/{scene_id}/design_spec response. */
export interface DesignSpecDoc {
  spec_version: number;
  scene_id: string;
  entries: SpecEntry[];
  updated_at: string | null;
}

export interface AssembledScene {
  splats: PositionedSplat[];
  /** Shell planes when the shell doc is present with status "ready";
   * null when absent OR unavailable. The absent-vs-unavailable
   * distinction stays readable on assets.shell — the room page's grace
   * window reads that, not this. */
  shell: ShellPlane[] | null;
  /** Fused objects that could not be placed or lack a fetchable splat —
   * surfaced in the UI rather than silently dropped. */
  unrenderable: FusedObject[];
}

/**
 * Map an assets response to the viewer's input: placed fused objects whose
 * splat URI has a signed URL become PositionedSplats; everything else is
 * reported as unrenderable. The shell doc, when ready, becomes ShellPlanes
 * (floor first, then walls) carrying each plane's parametric material —
 * measured albedo, roughness and confidence-gated family. Nothing
 * shell-borne is fetched or signed (decision 0069).
 */
export function assembleScene(assets: SceneAssets): AssembledScene {
  const splats: PositionedSplat[] = [];
  const unrenderable: FusedObject[] = [];
  for (const obj of assets.manifest.objects ?? []) {
    // Prefer the compressed tier, fall back to the PLY (decision 0126). Same
    // Gaussians either way -- SPZ is a re-encoding of the same splat, not a
    // reduced one -- so this is a wire-format choice and nothing else.
    const url = obj.splat_gcs_uri
      ? (assets.asset_urls_compressed?.[obj.splat_gcs_uri] ??
         assets.asset_urls[obj.splat_gcs_uri])
      : undefined;
    if (obj.placed && obj.world_transform && url) {
      splats.push({
        url,
        label: obj.label,
        position: obj.world_transform.position,
        rotation_xyzw: obj.world_transform.rotation_xyzw,
        scale: obj.world_transform.scale,
        ...(obj.splat_clip && obj.splat_clip.kind === "roomplan_box"
          ? {
              clip: {
                center_world: obj.splat_clip.center_world,
                half_extents_m: obj.splat_clip.half_extents_m,
                yaw_rad: obj.splat_clip.yaw_rad,
              },
            }
          : {}),
      });
    } else {
      unrenderable.push(obj);
    }
  }

  let shell: ShellPlane[] | null = null;
  const doc = assets.shell;
  if (doc && doc.status === "ready") {
    const toMaterial = (m: ShellMaterialEntry | undefined): ShellPlane["material"] => ({
      albedo_hex: m?.albedo_hex ?? null,
      roughness: m?.render?.roughness ?? 0.9,
      family: m?.family ?? null,
    });
    const planes: ShellPlane[] = [];
    if (doc.floor && (doc.floor.polygon?.length ?? 0) >= 3) {
      planes.push({
        kind: "floor",
        corners: doc.floor.polygon,
        material: toMaterial(doc.floor.material),
        openings: [],
        confidence:
          "confidence" in doc.floor ? (doc.floor.confidence ?? null) : null,
      });
    }
    for (const wall of doc.walls ?? []) {
      // v3 walls carry `polygon`; v2 walls carry `quad`. Both are
      // interior-wound world corners — the renderer's one input.
      const corners = "polygon" in wall ? wall.polygon : wall.quad;
      if ((corners?.length ?? 0) < 3) continue; // degenerate: skip, never guess
      planes.push({
        kind: "wall",
        corners,
        material: toMaterial(wall.material),
        openings: wall.openings ?? [],
        confidence: "confidence" in wall ? (wall.confidence ?? null) : null,
      });
    }
    if (planes.length > 0) shell = planes;
  }

  return { splats, shell, unrenderable };
}
