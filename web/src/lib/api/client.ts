/**
 * ApiClient: the app's only doorway to api-public.
 *
 * LiveApiClient speaks the real HTTP contract (Bearer auth, error bodies
 * of the form {error, detail}). MockApiClient lives in mock.ts. Pages
 * never call fetch directly — they go through this interface, so the mock
 * and live paths exercise identical code.
 *
 * Conversation (decision 0058): sendMessage awaits response HEADERS and
 * throws typed pre-stream errors (429/409/400/401) BEFORE returning the
 * iterable; the iterable covers only the stream phase, yielding normalized
 * GuestEvents. SSE parsing lives HERE and nowhere else.
 */

import type {
  ConversationSnapshot,
  ConversationTurn,
  GuestEvent,
  SceneAssets,
  SceneStatus,
  SceneSummary,
} from "./types";

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

/** 429 budget_exhausted: the guest rests. guestLine is server-authored
 * voice (rendered as speech); resetsAt is the mechanism's boundary. */
export class BudgetExhaustedError extends ApiError {
  constructor(
    public readonly guestLine: string,
    public readonly resetsAt: string,
  ) {
    super(429, "budget_exhausted", "daily conversation budget exhausted");
    this.name = "BudgetExhaustedError";
  }
}

/** 409 turn_in_flight: another window holds this conversation's turn. */
export class TurnInFlightError extends ApiError {
  constructor() {
    super(409, "turn_in_flight", "a turn is already in flight");
    this.name = "TurnInFlightError";
  }
}

export interface ApiClient {
  listScenes(limit?: number): Promise<SceneSummary[]>;
  getSceneByBundle(bundleId: string): Promise<SceneSummary>;
  /** Throws SceneNotReadyError until the scene reaches `ready`. */
  getSceneAssets(sceneId: string): Promise<SceneAssets>;
  /** Throws SceneNotReadyError until ready; 200-empty otherwise. */
  getConversation(sceneId: string): Promise<ConversationSnapshot>;
  /**
   * One conversation turn. Resolves once the stream is OPEN; pre-stream
   * failures throw typed errors (BudgetExhaustedError, TurnInFlightError,
   * SceneNotReadyError, ApiError) before any iterable exists. The iterable
   * ends after a terminal event (done/error).
   */
  sendMessage(
    sceneId: string,
    text: string,
    clientMsgId: string,
  ): Promise<AsyncIterable<GuestEvent>>;
}

export type TokenProvider = () => Promise<string | null>;

/** Parse one SSE block ("event:"/"data:" lines) into a GuestEvent.
 * Comments (": ping") and unknown event names return null. */
function parseSseBlock(block: string): GuestEvent | null {
  let name: string | null = null;
  let data: string | null = null;
  for (const line of block.split("\n")) {
    if (line.startsWith(":")) continue; // comment (keep-alive ping)
    if (line.startsWith("event: ")) name = line.slice("event: ".length);
    else if (line.startsWith("data: ")) data = line.slice("data: ".length);
  }
  if (!name || data === null) return null;
  try {
    const payload = JSON.parse(data) as Record<string, unknown>;
    if (name === "delta" && typeof payload.text === "string") {
      return { type: "delta", text: payload.text };
    }
    if (name === "done" && payload.turn) {
      return { type: "done", turn: payload.turn as ConversationTurn };
    }
    if (name === "error") {
      return { type: "error", code: String(payload.code ?? "unknown") };
    }
  } catch {
    return null;
  }
  return null; // unknown event name — the vocabulary may grow
}

/**
 * hand-parse text/event-stream from a fetch body (native EventSource is
 * GET-only and cannot carry the Authorization header — decision 0058).
 * A stream that dies without a terminal event yields connection_lost so
 * the composer can move to its confirming state.
 */
async function* parseSseStream(
  body: ReadableStream<Uint8Array>,
): AsyncGenerator<GuestEvent> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    for (;;) {
      let chunk: ReadableStreamReadResult<Uint8Array>;
      try {
        chunk = await reader.read();
      } catch {
        yield { type: "error", code: "connection_lost" };
        return;
      }
      if (chunk.done) break;
      buffer += decoder.decode(chunk.value, { stream: true });
      let sep = buffer.indexOf("\n\n");
      while (sep !== -1) {
        const event = parseSseBlock(buffer.slice(0, sep));
        buffer = buffer.slice(sep + 2);
        sep = buffer.indexOf("\n\n");
        if (event) {
          yield event;
          if (event.type === "done" || event.type === "error") return;
        }
      }
    }
    // Clean end without done/error: the turn's fate is unknown.
    yield { type: "error", code: "connection_lost" };
  } finally {
    reader.releaseLock();
  }
}

export class LiveApiClient implements ApiClient {
  constructor(
    private readonly baseUrl: string,
    private readonly getToken: TokenProvider,
  ) {}

  private async authHeader(): Promise<string> {
    const token = await this.getToken();
    if (!token) {
      throw new ApiError(401, "no_local_token", "not signed in");
    }
    return `Bearer ${token}`;
  }

  private throwTyped(status: number, body: Record<string, string>): never {
    if (status === 409 && body.error === "scene_not_ready") {
      throw new SceneNotReadyError(body.status as SceneStatus);
    }
    if (status === 409 && body.error === "turn_in_flight") {
      throw new TurnInFlightError();
    }
    if (status === 429 && body.error === "budget_exhausted") {
      throw new BudgetExhaustedError(body.guest_line, body.resets_at);
    }
    throw new ApiError(status, body.error ?? `http_${status}`, body.detail);
  }

  private async request(path: string): Promise<unknown> {
    const resp = await fetch(`${this.baseUrl}${path}`, {
      headers: { Authorization: await this.authHeader() },
    });
    const body = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      this.throwTyped(resp.status, body as Record<string, string>);
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

  async getConversation(sceneId: string): Promise<ConversationSnapshot> {
    return (await this.request(
      `/scenes/${sceneId}/conversation`,
    )) as ConversationSnapshot;
  }

  async sendMessage(
    sceneId: string,
    text: string,
    clientMsgId: string,
  ): Promise<AsyncIterable<GuestEvent>> {
    const resp = await fetch(
      `${this.baseUrl}/scenes/${sceneId}/conversation/messages`,
      {
        method: "POST",
        headers: {
          Authorization: await this.authHeader(),
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ text, client_msg_id: clientMsgId }),
      },
    );
    if (!resp.ok) {
      const body = await resp.json().catch(() => ({}));
      this.throwTyped(resp.status, body as Record<string, string>);
    }
    if (!resp.body) {
      throw new ApiError(0, "no_stream", "response had no readable body");
    }
    return parseSseStream(resp.body);
  }
}
