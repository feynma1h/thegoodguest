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
  scale: number; // uniform, splat-local -> world
}

/** One fused physical object from the manifest's scene-level array. */
export interface FusedObject {
  object_id: string;
  label: string;
  placed: boolean;
  method: "depth_fit" | "layout_triangulated" | null;
  reason?: string; // present when placed is false
  splat_gcs_uri: string | null;
  world_transform: WorldTransform | null;
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
 * One plane entry as scenes/{id}/shell.json carries it (decision 0066).
 * quad corners are wound so the front face points into the room; corner 0
 * is the texture origin (+U to corner 1, +V to corner 3).
 */
export interface ShellPlaneEntry {
  quad: [number, number, number][]; // 4 world-frame corners, meters
  texture_gcs_uri: string | null; // null when source is "unobserved"
  observed_fraction: number;
  inpainted_fraction: number;
  source: string; // "baked" | "unobserved"
  wall_id?: string; // walls only
  classification?: string | null; // walls only; ARKit verbatim
  y?: number; // floor only
}

/**
 * The room shell document, verbatim from the assets response's sibling
 * `shell` field. The distinction the room page relies on: the FIELD being
 * null/absent = the shell stage hasn't landed yet (brief grace window);
 * a document with status "unavailable" = never coming (keep the grid).
 */
export interface ShellDoc {
  shell_version: number;
  scene_id: string;
  status: "ready" | "unavailable";
  reason: string | null; // "no_geometry_source" | "capture_expired" | null
  method: string; // "arkit_planes" today
  floor: ShellPlaneEntry | null;
  walls: ShellPlaneEntry[];
  quality?: Record<string, number>;
}

/** GET /scenes/{scene_id}/assets response. */
export interface SceneAssets {
  scene_id: string;
  manifest: SceneManifest;
  /** Room shell sibling (decision 0066). Absent/null = not yet. */
  shell?: ShellDoc | null;
  asset_urls: Record<string, string>; // gs:// URI -> signed HTTPS URL
  expires_at: string; // ISO 8601
}

/**
 * Conversation stage 1 (decision 0058). One completed turn as the wire
 * carries it — the server's client projection; internal fields (usage,
 * model, versions) never appear here.
 */
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
  scale: number;
}

/**
 * Renderer-agnostic shell plane (the PositionedSplat trick applied to the
 * shell): four world corners plus a fetchable texture URL. SplatViewer
 * consumes ONLY this shape — nothing renderer-shaped leaks either way
 * (decision 0053's containment rule).
 */
export interface ShellPlane {
  kind: "floor" | "wall";
  corners: [number, number, number][]; // 4, front face toward the room
  /** Signed HTTPS texture URL; null = untextured ("unobserved" plane) —
   * the viewer gives it a neutral treatment, never a fake texture. */
  texture_url: string | null;
  observed_fraction: number;
  inpainted_fraction: number;
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
 * (floor first, then walls) with signed texture URLs resolved.
 */
export function assembleScene(assets: SceneAssets): AssembledScene {
  const splats: PositionedSplat[] = [];
  const unrenderable: FusedObject[] = [];
  for (const obj of assets.manifest.objects ?? []) {
    const url = obj.splat_gcs_uri ? assets.asset_urls[obj.splat_gcs_uri] : undefined;
    if (obj.placed && obj.world_transform && url) {
      splats.push({
        url,
        label: obj.label,
        position: obj.world_transform.position,
        rotation_xyzw: obj.world_transform.rotation_xyzw,
        scale: obj.world_transform.scale,
      });
    } else {
      unrenderable.push(obj);
    }
  }

  let shell: ShellPlane[] | null = null;
  const doc = assets.shell;
  if (doc && doc.status === "ready") {
    const toPlane = (kind: ShellPlane["kind"], e: ShellPlaneEntry): ShellPlane => ({
      kind,
      corners: e.quad,
      texture_url: e.texture_gcs_uri
        ? (assets.asset_urls[e.texture_gcs_uri] ?? null)
        : null,
      observed_fraction: e.observed_fraction,
      inpainted_fraction: e.inpainted_fraction,
    });
    const planes: ShellPlane[] = [];
    if (doc.floor) planes.push(toPlane("floor", doc.floor));
    for (const wall of doc.walls ?? []) planes.push(toPlane("wall", wall));
    if (planes.length > 0) shell = planes;
  }

  return { splats, shell, unrenderable };
}
