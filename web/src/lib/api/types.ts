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

/** GET /scenes/{scene_id}/assets response. */
export interface SceneAssets {
  scene_id: string;
  manifest: SceneManifest;
  asset_urls: Record<string, string>; // gs:// URI -> signed HTTPS URL
  expires_at: string; // ISO 8601
}

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

export interface AssembledScene {
  splats: PositionedSplat[];
  /** Fused objects that could not be placed or lack a fetchable splat —
   * surfaced in the UI rather than silently dropped. */
  unrenderable: FusedObject[];
}

/**
 * Map an assets response to the viewer's input: placed fused objects whose
 * splat URI has a signed URL become PositionedSplats; everything else is
 * reported as unrenderable.
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
  return { splats, unrenderable };
}
