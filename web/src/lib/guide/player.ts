/**
 * The bridge to the guide's player inside the diorama viewer (decision 0376).
 *
 * The viewer (the diorama branch's services/diorama/viewer) runs in a
 * same-origin frame and announces itself as `window.__diorama`. The guide's
 * player (packages/room-guide's web/player.js, embedded as it is) is injected
 * into that frame as a module, so it shares the viewer's three.js, and answers
 * as `window.__guidePlayer` once it fires `guide-player-ready`. Its contract
 * is the guide's: `play(plan)` moves pieces along a motion plan exactly as the
 * server checked it, `place(poses)` sets them at once, `show(focus)` lights up
 * pieces and spaces, `clear()` takes the lights away.
 *
 * Nothing here edits the viewer's files. The one change to its page is a style
 * rule hiding its own room name, capture time and caption, which the room
 * page already shows in the product's chrome.
 *
 * Read by: components/guide/GuideRoom.tsx.
 */

import { GUIDE_PLAYER_PATH } from "./switch";
import type { GuideFocus, GuidePose, MotionPlan } from "./types";

export interface GuidePlayer {
  play(plan: MotionPlan): Promise<boolean>;
  place(poses: Record<string, GuidePose>): Promise<boolean>;
  show(focus: GuideFocus): void;
  clear(): void;
}

type ViewerWindow = Window & { __diorama?: unknown; __guidePlayer?: GuidePlayer };

export const HIDE_VIEWER_CHROME = "#roomname, #captured, #card { display: none !important; }";

/** Wait for the viewer in `frame`, inject the player once, and hand it back.
 * Polls rather than listening, so a second caller (React runs effects twice in
 * development) finds the player the first one injected: a module script with
 * the same address never runs twice in one document. Rejects when the frame
 * holds a page that is not the viewer, when the viewer says it could not load
 * the room, after `timeoutMs`, and on `signal` abort. */
export function attachPlayer(
  frame: HTMLIFrameElement,
  { src = GUIDE_PLAYER_PATH, timeoutMs = 45_000, pollMs = 100, signal }: {
    src?: string;
    timeoutMs?: number;
    pollMs?: number;
    signal?: AbortSignal;
  } = {},
): Promise<GuidePlayer> {
  return new Promise((resolve, reject) => {
    const started = Date.now();
    const tick = () => {
      if (signal?.aborted) {
        reject(new Error("aborted"));
        return;
      }
      const win = frame.contentWindow as ViewerWindow | null;
      const doc = frame.contentDocument;
      if (win?.__guidePlayer) {
        resolve(win.__guidePlayer);
        return;
      }
      if (doc && doc.readyState === "complete" && doc.URL !== "about:blank") {
        if (!doc.getElementById("stage")) {
          reject(new Error("viewer_missing"));
          return;
        }
        if ((doc.getElementById("loading")?.textContent ?? "").startsWith("Could not load")) {
          reject(new Error("viewer_failed"));
          return;
        }
      }
      if (win?.__diorama && doc && !doc.querySelector("script[data-guide-player]")) {
        const style = doc.createElement("style");
        style.textContent = HIDE_VIEWER_CHROME;
        doc.head.appendChild(style);
        const script = doc.createElement("script");
        script.type = "module";
        script.src = src;
        script.dataset.guidePlayer = "";
        script.onerror = () => reject(new Error("player_unavailable"));
        doc.body.appendChild(script);
      }
      if (Date.now() - started > timeoutMs) {
        reject(new Error("viewer_timeout"));
        return;
      }
      window.setTimeout(tick, pollMs);
    };
    tick();
  });
}

/** Play a plan the way the guide's panel does: where the moved pieces stood is
 * drawn first, then they move. */
export async function playPlan(player: GuidePlayer | null, plan: MotionPlan | null): Promise<void> {
  if (!player || !plan) return;
  player.show({ footprints: plan.footprints ?? [] });
  await player.play(plan);
}
