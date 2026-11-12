/**
 * The diorama camera rig (local finish override): replaces free orbit with a
 * few settled corner views (lib/shellFinishViews.planViews) the person steps
 * between with arrows or dots, eased over ~0.9 s. Within a view a gentle drag
 * nudges the camera a few degrees and it springs back on release, so the
 * room still feels alive without ever showing its back or a bad angle.
 *
 * Owns: the camera lens/clip planes (a 27 m-away narrow lens needs near/far
 * scaled to the distance, or coplanar surfaces z-fight), OrbitControls limits,
 * the small DOM control, and the transition clock. Three.js comes in as a
 * parameter, as everywhere else in the finish override.
 */

import type * as THREE_NS from "three";

import { type CutawayWall } from "@/lib/shellFinish";
import {
  frameRoom,
  openAtDoor,
  planViews,
  shortestTurn,
  stepOrder,
  type ViewPreset,
  type WorldBox,
} from "@/lib/shellFinishViews";
import type { Vec3 } from "@/lib/shell3d";

type T = typeof THREE_NS;

interface OrbitLike {
  addEventListener(type: "end" | "change", fn: () => void): void;
  removeEventListener(type: "end" | "change", fn: () => void): void;
  target: THREE_NS.Vector3;
  enabled: boolean;
  enableZoom: boolean;
  enablePan: boolean;
  minAzimuthAngle: number;
  maxAzimuthAngle: number;
  minPolarAngle: number;
  maxPolarAngle: number;
  minDistance: number;
  maxDistance: number;
  getAzimuthalAngle(): number;
  getPolarAngle(): number;
  update(): boolean;
}

export interface ViewRig {
  /** Camera offset from the target for the first view. */
  initialOffset: THREE_NS.Vector3;
  /** Advance an in-flight transition; true while the camera is moving. */
  tick: (now: number) => boolean;
  goTo: (index: number) => void;
  dispose: () => void;
}

const FOV = 22;
const NUDGE_AZ = 0.1;
const NUDGE_EL = 0.05;
const MOVE_MS = 900;
const SPRING_MS = 380;

const ease = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);

export function createViewRig(
  THREE: T,
  a: {
    camera: THREE_NS.PerspectiveCamera;
    controls: OrbitLike;
    domParent: HTMLElement | null;
    walls: CutawayWall[];
    boxes: WorldBox[];
    floor: Vec3[];
    wallHeight: number;
    keep?: [number, number] | null;
    onChange: () => void;
  },
): ViewRig | null {
  let views: ViewPreset[] = stepOrder(a.keep ? planViews(a.walls, a.boxes, 4) : openAtDoor(planViews(a.walls, a.boxes, 4), a.walls));
  if (a.keep) {
    const forced = planViews(a.walls, a.boxes, 8).find((v) => v.keep[0] === a.keep![0] && v.keep[1] === a.keep![1]);
    if (forced) views = stepOrder([forced, ...views.filter((v) => v !== forced)]);
  }
  if (views.length === 0) return null;

  const { camera, controls } = a;
  const fr = frameRoom(a.floor, a.wallHeight, FOV);
  const target = new THREE.Vector3(...fr.target);
  camera.fov = FOV;
  // Near/far hug the room: depth precision is what keeps the wall and its
  // thickness slab from z-fighting at 27 m.
  camera.near = Math.max(0.5, fr.distance - fr.radius * 1.7);
  camera.far = fr.distance + fr.radius * 3;
  camera.updateProjectionMatrix();

  controls.enableZoom = false;
  controls.enablePan = false;
  controls.minDistance = controls.maxDistance = fr.distance;
  controls.target.copy(target);

  const place = (az: number, el: number) => {
    camera.position.set(
      target.x + Math.sin(az) * Math.cos(el) * fr.distance,
      target.y + Math.sin(el) * fr.distance,
      target.z + Math.cos(az) * Math.cos(el) * fr.distance,
    );
  };
  const offsetFor = (v: ViewPreset) =>
    new THREE.Vector3(Math.sin(v.azimuth) * Math.cos(v.elevation), Math.sin(v.elevation), Math.cos(v.azimuth) * Math.cos(v.elevation)).multiplyScalar(fr.distance);

  const clearLimits = () => {
    controls.minAzimuthAngle = -Infinity;
    controls.maxAzimuthAngle = Infinity;
    controls.minPolarAngle = 0;
    controls.maxPolarAngle = Math.PI;
  };
  const limitsFor = (v: ViewPreset) => {
    if (Math.abs(v.azimuth) + NUDGE_AZ < Math.PI) {
      controls.minAzimuthAngle = v.azimuth - NUDGE_AZ;
      controls.maxAzimuthAngle = v.azimuth + NUDGE_AZ;
    } else {
      controls.minAzimuthAngle = -Infinity;
      controls.maxAzimuthAngle = Infinity;
    }
    controls.minPolarAngle = Math.PI / 2 - v.elevation - NUDGE_EL;
    controls.maxPolarAngle = Math.PI / 2 - v.elevation + NUDGE_EL;
  };

  let index = 0;
  let move: { t0: number; ms: number; az0: number; el0: number; az1: number; el1: number } | null = null;
  clearLimits();
  place(views[0].azimuth, views[0].elevation);
  limitsFor(views[0]);

  const start = (v: ViewPreset, ms: number) => {
    clearLimits();
    controls.enabled = false;
    move = {
      t0: performance.now(),
      ms,
      az0: controls.getAzimuthalAngle(),
      el0: Math.PI / 2 - controls.getPolarAngle(),
      az1: v.azimuth,
      el1: v.elevation,
    };
    a.onChange();
  };

  const goTo = (i: number) => {
    index = ((i % views.length) + views.length) % views.length;
    start(views[index], MOVE_MS);
    paint();
  };

  const tick = (now: number) => {
    if (!move) return false;
    const t = Math.min(1, (now - move.t0) / move.ms);
    const e = ease(t);
    const az = move.az0 + shortestTurn(move.az0, move.az1) * e;
    const el = move.el0 + (move.el1 - move.el0) * e;
    place(az, el);
    a.onChange();
    if (t >= 1) {
      move = null;
      controls.enabled = true;
      limitsFor(views[index]);
    }
    return true;
  };

  // Release after a nudge: spring back to the exact view.
  const onEnd = () => {
    const v = views[index];
    const daz = Math.abs(shortestTurn(controls.getAzimuthalAngle(), v.azimuth));
    const del = Math.abs(Math.PI / 2 - controls.getPolarAngle() - v.elevation);
    if (daz + del > 0.004) start(v, SPRING_MS);
  };
  controls.addEventListener("end", onEnd);
  const onChangeEvt = () => a.onChange();
  controls.addEventListener("change", onChangeEvt);

  // --- The small control: ‹ ● ○ ○ ○ ›, in the dusk register of the room page
  // (decision 0361). Every target is 34px so a dot is easy to hit; the room
  // page keeps the control's region clear (RoomStage's rail sits beside it).
  let root: HTMLDivElement | null = null;
  const dots: HTMLButtonElement[] = [];
  const paint = () =>
    dots.forEach((d, i) => {
      const on = i === index;
      d.setAttribute("aria-pressed", String(on));
      const dot = d.firstElementChild as HTMLElement | null;
      if (dot) dot.style.background = on ? "#eef2f6" : "transparent";
    });
  if (a.domParent && views.length > 1) {
    root = document.createElement("div");
    root.setAttribute("role", "group");
    root.setAttribute("aria-label", "Views of the room");
    Object.assign(root.style, {
      position: "absolute",
      left: "50%",
      bottom: "22px",
      transform: "translateX(-50%)",
      display: "flex",
      alignItems: "center",
      gap: "2px",
      padding: "4px",
      borderRadius: "999px",
      background: "#18222e",
      border: "1px solid rgba(238,242,246,0.08)",
      userSelect: "none",
      zIndex: "15",
    } as CSSStyleDeclaration);
    const hit = {
      width: "34px",
      height: "34px",
      display: "grid",
      placeItems: "center",
      border: "0",
      borderRadius: "999px",
      background: "transparent",
      cursor: "pointer",
      padding: "0",
      color: "#eef2f6",
    } as CSSStyleDeclaration;
    const btn = (path: string, fn: () => void, aria: string) => {
      const b = document.createElement("button");
      b.type = "button";
      b.setAttribute("aria-label", aria);
      b.innerHTML = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${path}"/></svg>`;
      Object.assign(b.style, hit);
      b.onclick = fn;
      return b;
    };
    root.appendChild(btn("M15 6l-6 6 6 6", () => goTo(index - 1), "Previous view"));
    views.forEach((_, i) => {
      const d = document.createElement("button");
      d.type = "button";
      d.setAttribute("aria-label", `View ${i + 1}`);
      Object.assign(d.style, hit);
      const dot = document.createElement("span");
      Object.assign(dot.style, {
        display: "block",
        width: "9px",
        height: "9px",
        borderRadius: "50%",
        border: "1.5px solid #eef2f6",
        boxSizing: "border-box",
      } as CSSStyleDeclaration);
      d.appendChild(dot);
      d.onclick = () => goTo(i);
      dots.push(d);
      root!.appendChild(d);
    });
    root.appendChild(btn("M9 6l6 6-6 6", () => goTo(index + 1), "Next view"));
    a.domParent.appendChild(root);
    paint();
  }
  const onKey = (e: KeyboardEvent) => {
    if (e.key === "ArrowLeft") goTo(index - 1);
    else if (e.key === "ArrowRight") goTo(index + 1);
  };
  window.addEventListener("keydown", onKey);

  return {
    initialOffset: offsetFor(views[0]),
    tick,
    goTo,
    dispose: () => {
      controls.removeEventListener("end", onEnd);
      controls.removeEventListener("change", onChangeEvt);
      window.removeEventListener("keydown", onKey);
      root?.remove();
    },
  };
}
