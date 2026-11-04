/**
 * Draws a ShellFinish (lib/shellFinish.ts) onto the viewer's shell meshes:
 * painted walls with a faint grain and soft corner shading, baseboards,
 * framed door/window openings, and a floor drawn per its family. Called by
 * SplatViewer after it builds the flat shell; takes the three.js module as
 * an argument so the renderer library stays imported in one place
 * (decision 0053's containment rule) — this file only has type imports.
 *
 * Everything is DRAWN from the finish's few numbers: procedural canvases
 * with a seeded generator (the same finish draws the same room every time),
 * no photographs. What the drawing may not do is claim detail the scan did
 * not observe: paint is smooth, tile joints on walls are off, and trim and
 * slab sizes are the finish's declared design choices.
 */

import type * as THREE_NS from "three";

import type { ShellPlane } from "@/lib/api/types";
import type { MeshRegion } from "@/components/finishCompareHarness";
import { createViewRig, type ViewRig } from "@/components/shellFinishViewRig";
import type { WorldBox } from "@/lib/shellFinishViews";

type ViewRigControls = Parameters<typeof createViewRig>[1]["controls"];
import {
  DEFAULT_EXPOSURE,
  baseboardSpans,
  casingPieces,
  isRectangularWall,
  openingMetres,
  type FinishWall,
  type ShellFinish,
} from "@/lib/shellFinish";
import { projectToWallPlane, wallFrame } from "@/lib/shell3d";

type T = typeof THREE_NS;
type Mesh = THREE_NS.Mesh;

/** What SplatViewer holds on to: per-frame cutaway visibility, the staging
 * camera, and teardown. */
export interface FinishController {
  /** Hide wall trim/frames/slabs the camera sees from outside (the cutaway). */
  update: (camera: THREE_NS.Camera) => void;
  /** The diorama camera rig: fixed corner views (see shellFinishViewRig).
   * Returns the first view's camera offset, or null when the room has no corner. */
  stage: (a: {
    camera: THREE_NS.PerspectiveCamera;
    controls: ViewRigControls;
    domParent: HTMLElement | null;
    boxes: WorldBox[];
    onChange: () => void;
  }) => THREE_NS.Vector3 | null;
  /** Advance the rig's transition; true while the camera is moving. */
  tick: (now: number) => boolean;
  dispose: () => void;
}

export interface FinishableShellMesh {
  mesh: Mesh;
  plane: ShellPlane;
  extras: Mesh[];
}

// ------------------------------------------------------------ small tools --
function rng(seed: number) {
  // mulberry32: deterministic, fast, good enough for dither and speckle.
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Periodic value noise on an n x n lattice (tiles seamlessly). */
function makeNoise(seed: number, n: number) {
  const r = rng(seed);
  const g = Array.from({ length: n * n }, () => r());
  const at = (x: number, y: number) => g[(((y % n) + n) % n) * n + (((x % n) + n) % n)];
  return (x: number, y: number) => {
    const xi = Math.floor(x);
    const yi = Math.floor(y);
    const fx = x - xi;
    const fy = y - yi;
    const sx = fx * fx * (3 - 2 * fx);
    const sy = fy * fy * (3 - 2 * fy);
    const a = at(xi, yi) + (at(xi + 1, yi) - at(xi, yi)) * sx;
    const b = at(xi, yi + 1) + (at(xi + 1, yi + 1) - at(xi, yi + 1)) * sx;
    return a + (b - a) * sy;
  };
}

function hexToRgb(hex: string): [number, number, number] {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function canvas(w: number, h: number) {
  const c = document.createElement("canvas");
  c.width = w;
  c.height = h;
  const ctx = c.getContext("2d")!;
  return { c, ctx };
}

/** Per-channel (linear) compensation for the viewer's warm light rig. */
export const RIG_COMP: [number, number, number] = [1.0, 1.06, 1.2];

const clamp255 = (v: number) => (v < 0 ? 0 : v > 255 ? 255 : v);

// ------------------------------------------------------------- wall paint --
const PX_PER_M = 220;
const MAX_TEX = 1024;

/** One wall: paint above, an optional tiled band below (tiles, joints at a
 * reviewed pitch, a bright border line on top), the measured colours, a soft
 * wash and fine roller grain, and shading toward the corners, ceiling line
 * and floor. Returns the colour map and a roughness map (glossy tile,
 * matte paint). */
function wallTextures(
  THREE: T,
  wf: FinishWall,
  widthM: number,
  heightM: number,
  seed: number,
) {
  const w = Math.min(MAX_TEX, Math.max(64, Math.round(widthM * PX_PER_M)));
  const h = Math.min(MAX_TEX, Math.max(64, Math.round(heightM * PX_PER_M)));
  const { c, ctx } = canvas(w, h);
  const { c: rc, ctx: rctx } = canvas(w, h);
  const { c: bc, ctx: bctx } = canvas(w, h);
  bctx.fillStyle = "rgb(128,128,128)";
  bctx.fillRect(0, 0, w, h);
  const wn = wf.wainscot ?? null;
  const [pr, pg, pb] = hexToRgb(wf.paint.hex);
  const [tr, tg, tb] = wn ? hexToRgb(wn.tile_hex) : [0, 0, 0];
  const bandPx = wn ? Math.min(h, Math.round(wn.height_m * PX_PER_M)) : 0;
  const bandTop = h - bandPx; // canvas y of the border line (v up = canvas down)
  const tuPx = wn?.tile_u_m ? wn.tile_u_m * PX_PER_M : 0;
  const tvPx = wn?.tile_v_m ? wn.tile_v_m * PX_PER_M : 0;
  const img = ctx.createImageData(w, h);
  const wash = makeNoise(seed, 6);
  const rnd = rng(seed ^ 0x9e3779b9);
  const toneRnd = rng(seed ^ 0x51ed);
  const tones = new Map<number, number>();
  const toneOf = (cx: number, cy: number) => {
    const k = cy * 1000 + cx;
    let t = tones.get(k);
    if (t === undefined) {
      t = (toneRnd() - 0.5) * 0.03;
      tones.set(k, t);
    }
    return t;
  };
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const inBand = wn !== null && y >= bandTop;
      const lf = (wash((x / w) * 6, (y / h) * 6) - 0.5) * 0.03;
      const hf = (rnd() - 0.5) * 2 * wf.paint.grain * (inBand ? 0.35 : 1);
      let m = 1 + lf + hf;
      if (inBand && tuPx > 0 && tvPx > 0) {
        m += toneOf(Math.floor(x / tuPx), Math.floor((y - bandTop) / tvPx));
      }
      const i = (y * w + x) * 4;
      const [r0, g0, b0] = inBand ? [tr, tg, tb] : [pr, pg, pb];
      img.data[i] = clamp255(r0 * m);
      img.data[i + 1] = clamp255(g0 * m);
      img.data[i + 2] = clamp255(b0 * m);
      img.data[i + 3] = 255;
    }
  }
  ctx.putImageData(img, 0, 0);

  rctx.fillStyle = "rgb(219,219,219)"; // paint ~0.86
  rctx.fillRect(0, 0, w, h);
  if (wn) {
    rctx.fillStyle = "rgb(84,84,84)"; // glazed tile ~0.33
    rctx.fillRect(0, bandTop, w, bandPx);
    // Joints: hairlines at the reviewed pitch, counted DOWN from the border
    // line (a tiled wall is laid from its trim course).
    if (tuPx > 0 && tvPx > 0) {
      ctx.strokeStyle = wn.joint_hex;
      ctx.globalAlpha = 0.55;
      ctx.lineWidth = Math.max(1, 0.0045 * PX_PER_M);
      ctx.beginPath();
      for (let y = bandTop + tvPx; y < h; y += tvPx) {
        ctx.moveTo(0, y);
        ctx.lineTo(w, y);
      }
      for (let x = 0; x < w; x += tuPx) {
        ctx.moveTo(x, bandTop);
        ctx.lineTo(x, h);
      }
      ctx.stroke();
      ctx.globalAlpha = 1;
      // Relief: joints are recessed.
      bctx.strokeStyle = "rgb(64,64,64)";
      bctx.lineWidth = Math.max(1.5, 0.006 * PX_PER_M);
      bctx.beginPath();
      for (let y = bandTop + tvPx; y < h; y += tvPx) {
        bctx.moveTo(0, y);
        bctx.lineTo(w, y);
      }
      for (let x = 0; x < w; x += tuPx) {
        bctx.moveTo(x, bandTop);
        bctx.lineTo(x, h);
      }
      bctx.stroke();
    }
    // The border line: a thin light course along the top of the band.
    ctx.fillStyle = wn.border_hex;
    ctx.fillRect(0, bandTop - 0.006 * PX_PER_M, w, 0.014 * PX_PER_M);
    bctx.fillStyle = "rgb(210,210,210)"; // the border course stands proud
    bctx.fillRect(0, bandTop - 0.008 * PX_PER_M, w, 0.016 * PX_PER_M);
  }

  // Soft shading. Canvas y is down, texture v is up, so the floor edge is
  // the canvas bottom. A cool dark keeps shadows from going muddy.
  const shade = (x0: number, y0: number, x1: number, y1: number, rect: [number, number, number, number], a: number) => {
    const g = ctx.createLinearGradient(x0, y0, x1, y1);
    g.addColorStop(0, `rgba(30,32,48,${a})`);
    g.addColorStop(1, "rgba(30,32,48,0)");
    ctx.fillStyle = g;
    ctx.fillRect(...rect);
  };
  const sideW = Math.min(w * 0.5, 0.45 * PX_PER_M);
  shade(0, 0, sideW, 0, [0, 0, sideW, h], 0.13);
  shade(w, 0, w - sideW, 0, [w - sideW, 0, sideW, h], 0.13);
  const topH = 0.55 * PX_PER_M;
  shade(0, 0, 0, topH, [0, 0, w, topH], 0.10);
  const footH = 0.35 * PX_PER_M;
  shade(0, h, 0, h - footH, [0, h - footH, w, footH], 0.10);

  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = 8;
  const rough = new THREE.CanvasTexture(rc);
  rough.anisotropy = 4;
  const bump = new THREE.CanvasTexture(bc);
  bump.anisotropy = 4;
  return { tex, rough, bump };
}

// ------------------------------------------------------------------ floor --
/** One repeating tile of floor, drawn per family. Returns the texture and
 * how many metres one repeat covers (x, y of the canvas). */
function floorTexture(THREE: T, finish: ShellFinish) {
  const fl = finish.floor!;
  const st = fl.style;
  const [r0, g0, b0] = hexToRgb(fl.hex);
  const seed = st.seed >>> 0;
  const rnd = rng(seed);
  const kind = st.kind;
  const S = 1024;

  // Repeat geometry per family (metres per canvas side).
  let repW = 2.4;
  let repH = 2.4;
  if (kind === "wood") {
    const pw = st.plank_w_m ?? 0.14;
    repH = pw * 8;
    repW = 2.4;
  } else if (kind === "stone" || kind === "tile") {
    repW = (st.slab_u_m ?? 0.6) * 4;
    repH = (st.slab_v_m ?? 0.6) * 4;
  }
  const W = S;
  const H = kind === "wood" ? Math.round((S * repH) / repW) * 2 : S;
  const { c, ctx } = canvas(W, H);
  const { c: bc, ctx: bctx } = canvas(W, H);
  bctx.fillStyle = "rgb(140,140,140)";
  bctx.fillRect(0, 0, W, H);
  const img = ctx.createImageData(W, H);

  const lf = makeNoise(seed + 1, 8);
  const mf = makeNoise(seed + 2, 24);
  const slabPxX = kind === "wood" ? 0 : W / 4;
  const slabPxY = kind === "wood" ? 0 : H / 4;
  const plankPx = kind === "wood" ? H / 8 : 0;
  // Per-slab / per-plank tone offsets.
  const tone: number[] = Array.from({ length: 64 }, () => (rnd() - 0.5) * 2);
  const woodShift: number[] = Array.from({ length: 8 * 4 }, () => rnd());

  for (let y = 0; y < H; y++) {
    for (let x = 0; x < W; x++) {
      let m = 1;
      const cloud = (lf((x / W) * 8, (y / H) * 8) - 0.5) * 2; // -1..1
      const mid = (mf((x / W) * 24, (y / H) * 24) - 0.5) * 2;
      if (kind === "stone") {
        const sx = Math.floor(x / slabPxX);
        const sy = Math.floor(y / slabPxY);
        m += tone[sy * 4 + sx] * st.mottle * 0.28 + cloud * st.mottle * 0.22 + mid * st.mottle * 0.12;
      } else if (kind === "tile") {
        const sx = Math.floor(x / slabPxX);
        const sy = Math.floor(y / slabPxY);
        m += tone[sy * 4 + sx] * st.mottle * 0.4 + cloud * st.mottle * 0.3;
      } else if (kind === "wood") {
        const row = Math.floor(y / plankPx);
        // Stagger butt joints per row; plank tone per (row, segment).
        const seg = Math.floor((x + (row * 0.37 * W) % W) / (W / 2)) % 4;
        const v = woodShift[(row % 8) * 4 + seg];
        // Long grain streaks along x.
        const streak = (mf((x / W) * 3, (y / H) * 60) - 0.5) * 2;
        m += (v - 0.5) * 0.10 + streak * 0.035 + cloud * 0.02;
      } else if (kind === "concrete") {
        m += cloud * 0.045 + mid * 0.025;
      } else if (kind === "carpet") {
        m += (rnd() - 0.5) * 0.06 + cloud * 0.015;
      } else {
        m += cloud * 0.02;
      }
      const i = (y * W + x) * 4;
      img.data[i] = clamp255(r0 * m);
      img.data[i + 1] = clamp255(g0 * m);
      img.data[i + 2] = clamp255(b0 * m);
      img.data[i + 3] = 255;
    }
  }
  ctx.putImageData(img, 0, 0);

  // Joints.
  const joint = (x0: number, y0: number, x1: number, y1: number, a: number, wpx: number) => {
    ctx.strokeStyle = `rgba(40,38,36,${a})`;
    ctx.lineWidth = wpx;
    ctx.beginPath();
    ctx.moveTo(x0, y0);
    ctx.lineTo(x1, y1);
    ctx.stroke();
    bctx.strokeStyle = "rgb(60,60,60)"; // joints are recessed
    bctx.lineWidth = wpx * 1.4;
    bctx.beginPath();
    bctx.moveTo(x0, y0);
    bctx.lineTo(x1, y1);
    bctx.stroke();
  };
  if (kind === "stone" || kind === "tile") {
    const a = kind === "tile" ? 0.30 : 0.24;
    for (let k = 0; k <= 4; k++) {
      joint(k * slabPxX, 0, k * slabPxX, H, a, 2.2);
      joint(0, k * slabPxY, W, k * slabPxY, a, 2.2);
    }
  } else if (kind === "wood") {
    for (let k = 0; k <= 8; k++) joint(0, k * plankPx, W, k * plankPx, 0.28, 1.6);
    for (let row = 0; row < 8; row++) {
      for (let s = 0; s < 2; s++) {
        const x = (((row * 0.37 + s * 0.5) % 1) * W) | 0;
        joint(x, row * plankPx, x, (row + 1) * plankPx, 0.28, 1.4);
      }
    }
  }

  // Stone: cool veins, a few irregular stains and fine flecks. Stain and fleck
  // density come from the observed dark fraction of the floor (style.speckle).
  if (kind === "stone" && st.speckle > 0) {
    // Veins: long, thin, slightly cool lines wandering across the slab.
    for (let i = 0; i < 10; i++) {
      const dark = rnd() < 0.7;
      ctx.strokeStyle = dark ? `rgba(70,76,92,${0.05 + rnd() * 0.07})` : `rgba(255,255,255,${0.08 + rnd() * 0.08})`;
      ctx.lineWidth = 0.8 + rnd() * 2.2;
      ctx.beginPath();
      let x = rnd() * W;
      let y = rnd() * H;
      ctx.moveTo(x, y);
      for (let k = 0; k < 6; k++) {
        const nx = x + (rnd() - 0.35) * 200;
        const ny = y + (rnd() - 0.5) * 140;
        ctx.quadraticCurveTo(x + (nx - x) * 0.5 + (rnd() - 0.5) * 60, y + (ny - y) * 0.5 + (rnd() - 0.5) * 60, nx, ny);
        x = nx;
        y = ny;
      }
      ctx.stroke();
    }
    // Stains: soft, elongated, feathered patches — not hard-edged shapes.
    const blobs = Math.round(st.speckle * 160);
    for (let i = 0; i < blobs; i++) {
      const cx = rnd() * W;
      const cy = rnd() * H;
      const rad = 16 + rnd() * rnd() * 110;
      const sx = 0.7 + rnd() * 1.3;
      const rot = rnd() * Math.PI;
      const g = ctx.createRadialGradient(0, 0, 0, 0, 0, rad);
      const a0 = 0.07 + rnd() * 0.10;
      g.addColorStop(0, `rgba(58,60,68,${a0})`);
      g.addColorStop(0.6, `rgba(58,60,68,${a0 * 0.5})`);
      g.addColorStop(1, "rgba(58,60,68,0)");
      ctx.save();
      ctx.translate(cx, cy);
      ctx.rotate(rot);
      ctx.scale(sx, 1);
      ctx.fillStyle = g;
      ctx.beginPath();
      ctx.arc(0, 0, rad, 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();
    }
    // Fine flecks.
    const n = Math.round(st.speckle * 6000);
    for (let i = 0; i < n; i++) {
      const r = 0.5 + rnd() * rnd() * 1.8;
      ctx.fillStyle = `rgba(48,50,56,${0.10 + rnd() * 0.18})`;
      ctx.beginPath();
      ctx.ellipse(rnd() * W, rnd() * H, r * (1 + rnd()), r, rnd() * Math.PI, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
  tex.anisotropy = 16;
  const bump = new THREE.CanvasTexture(bc);
  bump.wrapS = bump.wrapT = THREE.RepeatWrapping;
  bump.anisotropy = 8;
  return { tex, bump, repW, repH: kind === "wood" ? repH * 2 : repH };
}

/** The longest horizontal edge's direction in the XZ plane: slabs and
 * planks lay along the room, not at an arbitrary world angle. */
function dominantAngle(corners: [number, number, number][]): number {
  let best = 0;
  let ang = 0;
  for (let i = 0; i < corners.length; i++) {
    const a = corners[i];
    const b = corners[(i + 1) % corners.length];
    const dx = b[0] - a[0];
    const dz = b[2] - a[2];
    const len = Math.hypot(dx, dz);
    if (len > best) {
      best = len;
      ang = Math.atan2(dz, dx);
    }
  }
  return ang;
}

// ------------------------------------------------------------ environment --
/** A small stand-in room built from the finish's own colours — paint walls,
 * the floor's colour, a soft ceiling and one bright window — prefiltered for
 * reflections. Glossy tile, varnished wood and polished stone reflect THIS,
 * so their sheen carries the room's colours instead of reflecting nothing.
 * It is a designed environment, not a capture of the real surroundings. */
export function roomEnvironment(THREE: T, renderer: THREE_NS.WebGLRenderer, finish: ShellFinish) {
  const env = new THREE.Scene();
  const flat = (hex: string, k = 1) => {
    const m = new THREE.MeshBasicMaterial({ color: new THREE.Color(hex).multiplyScalar(k), side: THREE.BackSide });
    m.toneMapped = false;
    return m;
  };
  const wall = finish.walls[0]?.paint.hex ?? "#c8d0e6";
  const floorHex = finish.floor?.hex ?? "#b8b8b4";
  const room = new THREE.Mesh(new THREE.BoxGeometry(5, 3, 5), [
    flat(wall), flat(wall), flat("#f4f2ee", 1.2), flat(floorHex), flat(wall), flat(wall),
  ]);
  env.add(room);
  const win = new THREE.Mesh(
    new THREE.PlaneGeometry(2.2, 1.4),
    new THREE.MeshBasicMaterial({ color: new THREE.Color(1, 0.97, 0.9).multiplyScalar(7), toneMapped: false }),
  );
  win.position.set(2.45, 0.2, 0.3);
  win.rotation.y = -Math.PI / 2;
  env.add(win);
  const pm = new THREE.PMREMGenerator(renderer);
  const rt = pm.fromScene(env, 0.03);
  pm.dispose();
  env.traverse((o) => {
    const m = o as THREE_NS.Mesh;
    if (m.isMesh) {
      m.geometry.dispose();
      for (const mm of Array.isArray(m.material) ? m.material : [m.material]) mm.dispose();
    }
  });
  return rt;
}

/** A soft warm wash on the floor where a window's light would fall:
 * the window rect projected along a gentle downward direction. Pure design
 * (the scan did not measure sun); kept faint. */
function windowGlow(
  THREE: T,
  corners: THREE_NS.Vector3[],
  floorY: number,
  dir: THREE_NS.Vector3,
) {
  const pts = corners.map((p) => {
    const t = (floorY - p.y) / dir.y;
    return new THREE.Vector3(p.x + dir.x * t, floorY + 0.003, p.z + dir.z * t);
  });
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(pts.flatMap((p) => [p.x, p.y, p.z]), 3));
  g.setAttribute("uv", new THREE.Float32BufferAttribute([0, 0, 1, 0, 1, 1, 0, 1], 2));
  g.setIndex([0, 2, 1, 0, 3, 2]);
  const { c, ctx } = canvas(128, 128);
  const grad = ctx.createRadialGradient(64, 64, 4, 64, 64, 64);
  grad.addColorStop(0, "rgba(255,244,222,1)");
  grad.addColorStop(0.55, "rgba(255,240,215,0.45)");
  grad.addColorStop(1, "rgba(255,238,210,0)");
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, 128, 128);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  const mat = new THREE.MeshBasicMaterial({
    map: tex,
    transparent: true,
    opacity: 0.22,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
    side: THREE.DoubleSide,
    toneMapped: false,
  });
  return new THREE.Mesh(g, mat);
}

// ----------------------------------------------------------------- driver --
/**
 * Dresses the already-built flat shell meshes. Returns a disposer for the
 * textures (the meshes' own geometry/material disposal is SplatViewer's
 * existing teardown, which walks `mesh` and `extras`).
 */
export function applyShellFinish(
  THREE: T,
  scene: THREE_NS.Scene,
  shellMeshes: FinishableShellMesh[],
  finish: ShellFinish,
  renderer: THREE_NS.WebGLRenderer,
): FinishController {
  const textures: THREE_NS.Texture[] = [];
  const envRt = roomEnvironment(THREE, renderer, finish);
  const envTex = envRt.texture;
  // A soft sky/ground wash so every wall reads about as bright from the
  // dollhouse orbit as from inside the room (the warm key light alone leaves
  // walls that face away from it grey).
  const hemi = new THREE.HemisphereLight(0xffffff, 0xe6e0d6, 0.9);
  scene.add(hemi);
  const glows: Mesh[] = [];
  const floorMesh = shellMeshes.find((m) => m.plane.kind === "floor");
  const floorY = floorMesh ? floorMesh.plane.corners[0][1] : 0;
  const exposure = finish.exposure ?? DEFAULT_EXPOSURE;
  // The light rig is warm (ambient 0xfff2df, key 0xffe7c4) and its
  // intensities dim diffuse surfaces; the finish's colours are the camera's
  // truth, so each channel is lifted by the rig's loss. Without this blue
  // paint reads grey and soft white reads cream.
  const gain = (m: THREE_NS.MeshStandardMaterial) =>
    m.color.setRGB(exposure * RIG_COMP[0], exposure * RIG_COMP[1], exposure * RIG_COMP[2]);

  const matCache = new Map<string, THREE_NS.MeshStandardMaterial>();
  /** A plain satin material in a measured colour, shared per colour. */
  const materialFor = (hex: string, roughness: number) => {
    const k = `${hex}|${roughness}`;
    let m = matCache.get(k);
    if (!m) {
      m = new THREE.MeshStandardMaterial({
        color: new THREE.Color(hex),
        roughness,
        metalness: 0,
        side: THREE.FrontSide,
        envMap: envTex,
        envMapIntensity: roughness < 0.5 ? 0.9 : 0.35,
      });
      m.color.multiply(new THREE.Color().setRGB(exposure * RIG_COMP[0], exposure * RIG_COMP[1], exposure * RIG_COMP[2]));
      matCache.set(k, m);
    }
    return m;
  };

  const box = (
    mat: THREE_NS.Material,
    frame: NonNullable<ReturnType<typeof wallFrame>>,
    cu: number,
    cv: number,
    lenU: number,
    lenV: number,
    depth: number,
    off = 0,
  ) => {
    const geom = new THREE.BoxGeometry(lenU, lenV, depth);
    const mesh = new THREE.Mesh(geom, mat);
    const n = new THREE.Vector3(...frame.normal);
    const u = new THREE.Vector3(...frame.axisU);
    const up = new THREE.Vector3(0, 1, 0);
    // Local X along the wall, Y up, Z out of the wall toward the room.
    mesh.setRotationFromMatrix(new THREE.Matrix4().makeBasis(u, up, n));
    mesh.position
      .set(...frame.origin)
      .addScaledVector(u, cu)
      .addScaledVector(up, cv)
      .addScaledVector(n, depth / 2 + off);
    return mesh;
  };

  let wallIdx = 0;
  const walls3d: { frame: NonNullable<ReturnType<typeof wallFrame>>; sm: FinishableShellMesh; slab: Mesh | null; centre: THREE_NS.Vector3 }[] = [];
  const slabMat = materialFor(finish.staging?.cap_hex ?? "#ece8e0", 0.75);
  const slabT = finish.staging?.wall_thickness_m ?? 0.12;
  shellMeshes.forEach((sm) => {
    const { mesh, plane } = sm;
    if (plane.kind === "floor") {
      if (!finish.floor) return;
      const { tex, bump, repW, repH } = floorTexture(THREE, finish);
      textures.push(tex, bump);
      const pos = mesh.geometry.getAttribute("position");
      const ang = dominantAngle(plane.corners);
      const [ca, sa] = [Math.cos(ang), Math.sin(ang)];
      const uvs = new Float32Array(pos.count * 2);
      for (let i = 0; i < pos.count; i++) {
        const x = pos.getX(i);
        const z = pos.getZ(i);
        const along = x * ca + z * sa;
        const across = -x * sa + z * ca;
        uvs[i * 2] = along / repW;
        uvs[i * 2 + 1] = across / repH;
      }
      mesh.geometry.setAttribute("uv", new THREE.BufferAttribute(uvs, 2));
      (mesh.material as THREE_NS.Material).dispose();
      const m = new THREE.MeshStandardMaterial({
        map: tex,
        bumpMap: bump,
        bumpScale: 1.2,
        envMap: envTex,
        envMapIntensity: finish.floor.family === "stone" ? 0.7 : 0.3,
        roughness: finish.floor.family === "stone" ? 0.34 : (plane.material.roughness ?? 0.6),
        metalness: 0,
        side: THREE.FrontSide,
        depthWrite: true,
      });
      gain(m);
      mesh.material = m;
      mesh.userData.region = { whole: "floor" } satisfies MeshRegion;
      return;
    }

    // ---- wall
    const wf = finish.walls[wallIdx++];
    if (!wf) return;
    const frame = wallFrame(plane.corners);
    if (!frame) return;
    const pos = mesh.geometry.getAttribute("position");
    const proj = projectToWallPlane(plane.corners, frame);
    const uvs = new Float32Array(pos.count * 2);
    for (let i = 0; i < pos.count; i++) {
      // Geometry positions are the polygon corners, in order.
      uvs[i * 2] = proj[i][0] / frame.widthM;
      uvs[i * 2 + 1] = proj[i][1] / frame.heightM;
    }
    mesh.geometry.setAttribute("uv", new THREE.BufferAttribute(uvs, 2));
    const seed = (finish.floor?.style.seed ?? 7) + wallIdx * 977;
    const { tex, rough, bump } = wallTextures(THREE, wf, frame.widthM, frame.heightM, seed);
    textures.push(tex, rough, bump);
    (mesh.material as THREE_NS.Material).dispose();
    const paint = new THREE.MeshStandardMaterial({
      map: tex,
      roughnessMap: rough,
      roughness: 1,
      bumpMap: bump,
      bumpScale: 1.0,
      envMap: envTex,
      envMapIntensity: 0.16,
      metalness: 0,
      side: THREE.FrontSide,
      depthWrite: true,
    });
    gain(paint);
    mesh.material = paint;
    mesh.userData.region = (wf.wainscot
      ? { wall: { bandFrac: Math.min(1, wf.wainscot.height_m / frame.heightM) } }
      : { whole: "paint" }) satisfies MeshRegion;

    // The flat opening insets give way to real framed openings.
    for (const old of sm.extras) {
      scene.remove(old);
      old.geometry.dispose();
      (old.material as THREE_NS.Material).dispose();
    }
    sm.extras.length = 0;

    // Diorama wall thickness: a slab behind the wall, its top is the pale cut
    // edge. Hidden with the rest of the wall's extras when the camera is outside.
    const slab = box(slabMat, frame, frame.widthM / 2, frame.heightM / 2, frame.widthM + 2 * slabT, frame.heightM, slabT, -slabT - 0.004);
    scene.add(slab);
    walls3d.push({
      frame,
      sm,
      slab,
      centre: new THREE.Vector3(...frame.origin)
        .addScaledVector(new THREE.Vector3(...frame.axisU), frame.widthM / 2)
        .add(new THREE.Vector3(0, frame.heightM / 2, 0)),
    });

    const rects = plane.openings.map((o) => openingMetres(frame, o.rect_uv));
    const add = (m: Mesh) => {
      scene.add(m);
      sm.extras.push(m);
    };
    const { baseboard_d_m: bd, casing_w_m: cw, casing_d_m: cd } = finish.trim;

    // A baseboard only where the scan has one (finish.walls[].baseboard).
    if (wf.baseboard && isRectangularWall(plane.corners, frame)) {
      const bbMat = materialFor(wf.baseboard.hex, 0.48);
      const bbh = wf.baseboard.height_m;
      for (const [a, b] of baseboardSpans(frame.widthM, rects, cw)) {
        // Board plus a thin cap that overhangs it: reads as a profile.
        add(box(bbMat, frame, (a + b) / 2, bbh / 2, b - a, bbh, bd));
        add(box(bbMat, frame, (a + b) / 2, bbh + 0.006, b - a, 0.012, bd + 0.006));
      }
    }

    plane.openings.forEach((op, k) => {
      const r = rects[k];
      const fo = wf.openings.find((o) => o.index === k);
      const isWindow = op.classification === "window";
      const leafHex = (isWindow ? fo?.glass_hex : fo?.leaf_hex) ?? fo?.leaf_hex ?? "#8a6a4a";
      const frameHex = fo?.frame_hex ?? null;
      // Leaf: a flat panel set slightly proud of the wall. A window gets its
      // sash drawn as a border in the measured frame colour; both get a
      // soft inner shadow so they read as sitting in the opening.
      const lw = r.u1 - r.u0;
      const lh = r.v1 - r.v0;
      const { c, ctx } = canvas(128, 128);
      const [lr, lg, lb] = hexToRgb(leafHex);
      ctx.fillStyle = `rgb(${lr},${lg},${lb})`;
      ctx.fillRect(0, 0, 128, 128);
      if (isWindow) {
        const g = ctx.createLinearGradient(0, 0, 0, 128);
        g.addColorStop(0, "rgba(255,255,255,0.18)");
        g.addColorStop(1, "rgba(255,255,255,0)");
        ctx.fillStyle = g;
        ctx.fillRect(0, 0, 128, 128);
        if (frameHex) {
          const bx = Math.min(30, (0.06 / lw) * 128);
          const by = Math.min(30, (0.06 / lh) * 128);
          ctx.fillStyle = frameHex;
          ctx.fillRect(0, 0, 128, by);
          ctx.fillRect(0, 128 - by, 128, by);
          ctx.fillRect(0, 0, bx, 128);
          ctx.fillRect(128 - bx, 0, bx, 128);
        }
      }
      const { c: lbc, ctx: lbx } = canvas(128, 128);
      lbx.fillStyle = "rgb(128,128,128)";
      lbx.fillRect(0, 0, 128, 128);
      // Reviewed panel layout (finish_hints): bevelled rectangles, light on
      // the top/left edge, dark on the bottom/right, as raised-panel doors read.
      for (const [pu0, pv0, pu1, pv1] of fo?.panels ?? []) {
        const x0 = pu0 * 128, x1 = pu1 * 128, y0 = (1 - pv1) * 128, y1 = (1 - pv0) * 128;
        ctx.lineWidth = 2.5;
        ctx.strokeStyle = "rgba(255,225,190,0.35)";
        ctx.beginPath(); ctx.moveTo(x0, y1); ctx.lineTo(x0, y0); ctx.lineTo(x1, y0); ctx.stroke();
        ctx.strokeStyle = "rgba(30,12,0,0.45)";
        ctx.beginPath(); ctx.moveTo(x1, y0); ctx.lineTo(x1, y1); ctx.lineTo(x0, y1); ctx.stroke();
        // Relief: the panel field sits back from its frame.
        lbx.fillStyle = "rgb(92,92,92)";
        lbx.fillRect(x0 + 3, y0 + 3, x1 - x0 - 6, y1 - y0 - 6);
      }
      const inner = (x0: number, y0: number, x1: number, y1: number, rect: [number, number, number, number]) => {
        const g = ctx.createLinearGradient(x0, y0, x1, y1);
        g.addColorStop(0, "rgba(20,20,28,0.30)");
        g.addColorStop(1, "rgba(20,20,28,0)");
        ctx.fillStyle = g;
        ctx.fillRect(...rect);
      };
      inner(0, 0, 14, 0, [0, 0, 14, 128]);
      inner(128, 0, 114, 0, [114, 0, 14, 128]);
      inner(0, 0, 0, 14, [0, 0, 128, 14]);
      inner(0, 128, 0, 114, [0, 114, 128, 14]);
      const leafBump = new THREE.CanvasTexture(lbc);
      textures.push(leafBump);
      const leafTex = new THREE.CanvasTexture(c);
      leafTex.colorSpace = THREE.SRGBColorSpace;
      textures.push(leafTex);
      const leafMat = new THREE.MeshStandardMaterial({
        map: leafTex,
        bumpMap: leafBump,
        bumpScale: 1.0,
        envMap: envTex,
        envMapIntensity: isWindow ? 0.9 : 0.8,
        roughness: isWindow ? 0.2 : 0.3, // polished wood / glass
        metalness: 0,
        side: THREE.FrontSide,
      });
      gain(leafMat);
      const leafMesh = box(leafMat, frame, (r.u0 + r.u1) / 2, (r.v0 + r.v1) / 2, lw, lh, 0.004, 0.004);
      leafMesh.userData.region = { whole: isWindow ? "glass" : "door" } satisfies MeshRegion;
      add(leafMesh);

      if (isWindow && floorMesh) {
        const up = new THREE.Vector3(0, 1, 0);
        const n = new THREE.Vector3(...frame.normal);
        const u = new THREE.Vector3(...frame.axisU);
        const o = new THREE.Vector3(...frame.origin);
        const at = (uu: number, vv: number) => o.clone().addScaledVector(u, uu).addScaledVector(up, vv);
        const dir = n.clone().multiplyScalar(0.75).add(new THREE.Vector3(0, -0.65, 0)).normalize();
        const glow = windowGlow(THREE, [at(r.u0, r.v0), at(r.u1, r.v0), at(r.u1, r.v1), at(r.u0, r.v1)], floorY, dir);
        scene.add(glow);
        glows.push(glow);
      }

      // Casing only where the scan shows one (opening.casing_hex).
      if (fo?.casing_hex) {
        const casingMat = materialFor(fo.casing_hex, 0.4);
        for (const p of casingPieces(r, frame.widthM, frame.heightM, cw)) {
          const cm = box(casingMat, frame, p.cu, p.cv, p.w, p.h, cd + p.deeper, 0.001);
          cm.userData.region = { whole: "casing" } satisfies MeshRegion;
          add(cm);
        }
      }
    });
  });

  // ---- The plinth: a floor slab (outline offset out to the wall thickness) and
  // a soft shadow on the ground beneath it.
  const owned: Mesh[] = walls3d.map((w) => w.slab).filter((m): m is Mesh => !!m);
  let floorSlab: Mesh | null = null;
  let groundShadow: Mesh | null = null;
  if (floorMesh) {
    const outline = offsetPolygonXZ(floorMesh.plane.corners, slabT);
    const shape = new THREE.Shape(outline.map(([x, z]) => new THREE.Vector2(x, z)));
    const slabDepth = 0.1;
    const geo = new THREE.ExtrudeGeometry(shape, { depth: slabDepth, bevelEnabled: false });
    geo.rotateX(Math.PI / 2);
    geo.translate(0, floorY - 0.0006, 0);
    floorSlab = new THREE.Mesh(geo, slabMat);
    scene.add(floorSlab);
    owned.push(floorSlab);

    const xs = outline.map((p) => p[0]);
    const zs = outline.map((p) => p[1]);
    const cx = (Math.min(...xs) + Math.max(...xs)) / 2;
    const cz = (Math.min(...zs) + Math.max(...zs)) / 2;
    const sz = Math.max(Math.max(...xs) - Math.min(...xs), Math.max(...zs) - Math.min(...zs)) * 1.9;
    const { c: sc, ctx: sx } = canvas(256, 256);
    const rg = sx.createRadialGradient(128, 128, 40, 128, 128, 128);
    rg.addColorStop(0, "rgba(40,36,30,0.55)");
    rg.addColorStop(0.45, "rgba(40,36,30,0.22)");
    rg.addColorStop(1, "rgba(40,36,30,0)");
    sx.fillStyle = rg;
    sx.fillRect(0, 0, 256, 256);
    const stex = new THREE.CanvasTexture(sc);
    textures.push(stex);
    groundShadow = new THREE.Mesh(
      new THREE.PlaneGeometry(sz, sz),
      new THREE.MeshBasicMaterial({ map: stex, transparent: true, depthWrite: false, toneMapped: false }),
    );
    groundShadow.rotation.x = -Math.PI / 2;
    groundShadow.position.set(cx, floorY - slabDepth - 0.004, cz);
    scene.add(groundShadow);
    owned.push(groundShadow);
  }

  const update = (camera: THREE_NS.Camera) => {
    for (const w of walls3d) {
      const facing = w.frame.normal[0] * (camera.position.x - w.centre.x) + w.frame.normal[2] * (camera.position.z - w.centre.z) > 0;
      if (w.slab) w.slab.visible = facing;
      for (const e of w.sm.extras) e.visible = facing;
    }
  };

  let rig: ViewRig | null = null;
  const stage: FinishController["stage"] = ({ camera, controls, domParent, boxes, onChange }) => {
    if (!floorMesh) return null;
    const wallPlanes = shellMeshes.filter((m) => m.plane.kind === "wall").map((m) => m.plane);
    const wallH = Math.max(...wallPlanes.flatMap((p) => p.corners.map((c) => c[1]))) - floorY;
    rig = createViewRig(THREE, {
      camera,
      controls,
      domParent,
      walls: wallPlanes.map((p) => ({ corners: p.corners, openings: p.openings })),
      boxes,
      floor: floorMesh.plane.corners,
      wallHeight: wallH,
      keep: finish.staging?.keep ?? null,
      onChange,
    });
    return rig ? rig.initialOffset : null;
  };
  const tick = (now: number) => (rig ? rig.tick(now) : false);

  const dispose = () => {
    rig?.dispose();
    for (const t of textures) t.dispose();
    for (const m of matCache.values()) m.dispose();
    for (const gm of glows) {
      scene.remove(gm);
      gm.geometry.dispose();
      (gm.material as THREE_NS.Material).dispose();
    }
    for (const o of owned) {
      scene.remove(o);
      o.geometry.dispose();
      if (o === groundShadow) (o.material as THREE_NS.Material).dispose();
    }
    scene.remove(hemi);
    hemi.dispose();
    envRt.dispose();
  };
  return { update, stage, tick, dispose };
}

/** A simple polygon pushed out by `t` metres in the XZ plane (each edge moved
 * along its outward normal; neighbours re-intersected). Fine for the convex
 * and mildly concave outlines RoomPlan produces. */
function offsetPolygonXZ(corners: [number, number, number][], t: number): [number, number][] {
  const p = corners.map((c) => [c[0], c[2]] as [number, number]);
  let area = 0;
  for (let i = 0; i < p.length; i++) {
    const [ax, az] = p[i];
    const [bx, bz] = p[(i + 1) % p.length];
    area += ax * bz - bx * az;
  }
  const sgn = area > 0 ? 1 : -1; // outward normal of edge d is sgn * (dz, -dx)
  const lines = p.map(([ax, az], i) => {
    const [bx, bz] = p[(i + 1) % p.length];
    const dx = bx - ax;
    const dz = bz - az;
    const len = Math.hypot(dx, dz) || 1;
    const nx = (sgn * dz) / len;
    const nz = (-sgn * dx) / len;
    return { x: ax + nx * t, z: az + nz * t, dx, dz };
  });
  return p.map((_, i) => {
    const a = lines[(i + lines.length - 1) % lines.length];
    const b = lines[i];
    const det = a.dx * b.dz - a.dz * b.dx;
    if (Math.abs(det) < 1e-9) return [b.x, b.z] as [number, number];
    const tt = ((b.x - a.x) * b.dz - (b.z - a.z) * b.dx) / det;
    return [a.x + a.dx * tt, a.z + a.dz * tt] as [number, number];
  });
}
