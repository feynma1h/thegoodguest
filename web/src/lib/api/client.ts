/**
 * ApiClient: the app's only doorway to api-public.
 *
 * LiveApiClient speaks the real HTTP contract (Bearer auth, error bodies
 * of the form {error, detail}). MockApiClient lives in mock.ts. Pages
 * never call fetch directly — they go through this interface, so the mock
 * and live paths exercise identical code.
 */

import type { SceneAssets, SceneStatus, SceneSummary } from "./types";

/** Structured API failure: HTTP status + the server's error code. */
export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    detail?: string,
  ) {
    super(detail ? `${code}: ${detail}` : code);
    this.name = "ApiError";
  }
}

/** 409 scene_not_ready, carrying the scene's current status. */
export class SceneNotReadyError extends ApiError {
  constructor(public readonly sceneStatus: SceneStatus) {
    super(409, "scene_not_ready", `scene is ${sceneStatus}`);
    this.name = "SceneNotReadyError";
  }
}

export interface ApiClient {
  listScenes(limit?: number): Promise<SceneSummary[]>;
  getSceneByBundle(bundleId: string): Promise<SceneSummary>;
  /** Throws SceneNotReadyError until the scene reaches `ready`. */
  getSceneAssets(sceneId: string): Promise<SceneAssets>;
}

export type TokenProvider = () => Promise<string | null>;

export class LiveApiClient implements ApiClient {
  constructor(
    private readonly baseUrl: string,
    private readonly getToken: TokenProvider,
  ) {}

  private async request(path: string): Promise<unknown> {
    const token = await this.getToken();
    if (!token) {
      throw new ApiError(401, "no_local_token", "not signed in");
    }
    const resp = await fetch(`${this.baseUrl}${path}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const body = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      const rec = body as Record<string, string>;
      if (resp.status === 409 && rec.error === "scene_not_ready") {
        throw new SceneNotReadyError(rec.status as SceneStatus);
      }
      throw new ApiError(resp.status, rec.error ?? `http_${resp.status}`, rec.detail);
    }
    return body;
  }

  async listScenes(limit = 50): Promise<SceneSummary[]> {
    const body = (await this.request(`/scenes?limit=${limit}`)) as {
      scenes: SceneSummary[];
    };
    return body.scenes;
  }

  async getSceneByBundle(bundleId: string): Promise<SceneSummary> {
    return (await this.request(`/scenes/by-bundle/${bundleId}`)) as SceneSummary;
  }

  async getSceneAssets(sceneId: string): Promise<SceneAssets> {
    return (await this.request(`/scenes/${sceneId}/assets`)) as SceneAssets;
  }
}
