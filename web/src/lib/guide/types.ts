/**
 * The room guide's wire contract (decision 0376), mirrored from api-public.
 *
 * Sources of truth (keep in sync):
 *   - services/api-public/public_server.py — the /scenes/{id}/guide routes'
 *     docstrings: the snapshot, the SSE events, the button responses.
 *   - services/api-public/guide_session.py — the panel's view of a turn
 *     (fold_events) and a card's status (card_status).
 *   - packages/room-guide/thegoodguest_room_guide/motion.py — plan_json, the
 *     viewer's contract: per piece, keyframes of time, position and turn, eased
 *     with smoothstep between them, never overshooting.
 *
 * Read by: lib/api/client.ts, lib/guide/*, components/guide/GuideRoom.tsx.
 */

/** A piece's place in the room: the diorama viewer's group position and yaw. */
export interface GuidePose {
  x: number;
  y: number;
  z: number;
  yaw: number;
}

/** A rectangle on the floor, for footprints and the spaces findings are about. */
export interface FloorRect {
  x: number;
  z: number;
  hx: number;
  hz: number;
  yaw: number;
}

export interface PlanKey extends GuidePose {
  t: number;
}

/** motion.py's plan_json, plus what the server adds for the player. */
export interface MotionPlan {
  plan_version: number;
  easing: "smoothstep";
  duration: number;
  order: string[];
  tracks: Record<string, PlanKey[]>;
  checked: { frames: number; fps: number };
  /** The wall each moved wall item hangs on afterwards. */
  walls?: Record<string, string>;
  /** Where the moved pieces stood, drawn dashed while they move. */
  footprints?: FloorRect[];
  methods?: Record<string, string>;
}

/** What the guide lights up on screen. */
export interface GuideFocus {
  pieces?: string[];
  zones?: FloorRect[];
  footprints?: FloorRect[];
}

/** "ready" while the room is as it was when the card was offered, "shown"
 * while its change is on screen, "stale" once the room has moved on, "gone"
 * when the server no longer keeps it. */
export type CardStatus = "ready" | "shown" | "stale" | "gone";

/** A "Show me" card: a change the room solved and checked, in its words. */
export interface GuideCard {
  id: string;
  words: string[];
  fixes: string[];
  adds: string[];
  leaves: string[];
  effort: string;
  goal: string;
  better: number;
  status?: CardStatus;
}

export type GuideItem =
  | { kind: "say"; text: string }
  | { kind: "note"; text: string }
  | { kind: "card"; card: GuideCard };

/** One kept turn as the panel shows it. `person` is null for the opening. */
export interface GuideTurnView {
  turn_index: number;
  client_msg_id: string;
  opening: boolean;
  person: string | null;
  items: GuideItem[];
}

/** The room as it stands in the conversation. */
export interface GuideState {
  poses: Record<string, GuidePose>;
  can_undo: boolean;
  cards: Record<string, CardStatus>;
}

/** GET /scenes/{id}/guide. */
export interface GuideSnapshot {
  scene_id: string;
  room: string;
  /** The room's floor area in square metres, from the scene's footprint. */
  floor_m2: number;
  turn_count: number;
  transcript: GuideTurnView[];
  state: GuideState;
  rested_until: string | null;
  busy: boolean;
}

/** POST /scenes/{id}/guide/show and /undo. */
export interface GuideMove {
  plan: MotionPlan | null;
  state: GuideState;
}

/** One event of a streamed turn, normalized by the client. */
export type GuideEvent =
  | { type: "delta"; text: string }
  | { type: "card"; card: GuideCard }
  | { type: "play"; plan: MotionPlan | null; state: GuideState }
  | { type: "focus"; focus: GuideFocus }
  | { type: "note"; text: string }
  | { type: "done"; turnIndex: number; clientMsgId: string; state: GuideState }
  | { type: "error"; code: string };
