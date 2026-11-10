/**
 * The landing's sample room: an authored, hand-built room (never a person's
 * scan) drawn the way the product draws a finished room, so a visitor can
 * turn a room in their hands before they have scanned one.
 *
 * It copies the product's diorama camera (lib/shellFinishViews.ts and
 * components/shellFinishViewRig.ts): a 22 degree lens, 24 degrees above the
 * horizon, aimed at the room's centre at 0.45 x the ceiling height, framed by
 * the same `frameRoom` distance, and four settled corner views along the
 * room's diagonals. The two walls nearest the camera are cut down to stubs. A
 * stage may start in free rotation; once a view is chosen it steps between the
 * four views, and a drag only nudges the camera and springs back.
 *
 * Three.js comes in as a parameter, as in the finish override. The one module
 * that loads it for this scene is components/SampleRoom.tsx — the second
 * three.js entry point after SplatViewer, and the only one that never draws a
 * person's room (decision 0361).
 *
 * No two surfaces share a plane (the plinth sits under the floor, not at it),
 * so nothing z-fights, and the camera never drifts on its own.
 */

import type * as T from "three";
import type { OrbitControls as OrbitControlsT } from "three/addons/controls/OrbitControls.js";

export interface SampleRoomLib {
  THREE: typeof import("three");
  OrbitControls: typeof import("three/addons/controls/OrbitControls.js").OrbitControls;
  RoundedBoxGeometry: typeof import("three/addons/geometries/RoundedBoxGeometry.js").RoundedBoxGeometry;
  RoomEnvironment: typeof import("three/addons/environments/RoomEnvironment.js").RoomEnvironment;
}

export type SampleRoomStage = "outline" | "shell" | "furnished";
export type SampleRoomMode = "day" | "night";

export interface SampleRoomOptions {
  mode?: SampleRoomMode;
  stage?: SampleRoomStage;
  /** Stand the room up (outline, walls, pieces) when the stage is first seen. */
  reveal?: boolean;
  interactive?: boolean;
  labels?: boolean;
  removed?: string[];
  /** Start in free rotation rather than locked to a view. */
  free?: boolean;
  view?: number;
  /** >1 frames the room closer. */
  fit?: number;
  /** Shift the room right by this fraction of the stage's width (wide stages only). */
  shift?: number;
  onView?: (view: number) => void;
}

export interface SampleRoomHandle {
  setMode: (mode: SampleRoomMode) => void;
  setStage: (stage: SampleRoomStage) => void;
  setRemoved: (ids: string[]) => void;
  replay: (to?: SampleRoomStage) => void;
  goTo: (view: number) => void;
  dispose: () => void;
}

export const VIEW_COUNT = 4;

const W = 4.4, D = 3.6, H = 2.6, T_WALL = 0.12;
const X0 = -W / 2, X1 = W / 2, Z0 = -D / 2, Z1 = D / 2;
const WIN = { x0: 0.3, x1: 1.7, y0: 0.88, y1: 2.24 };
const DOOR = { z0: 0.42, z1: 1.32, y1: 2.06 };

const FOV = 22;
const ELEV = (24 * Math.PI) / 180;
const RADIUS = Math.hypot(W / 2, D / 2, H / 2 + 0.05);
const BASE_DIST = (RADIUS / Math.tan((FOV * Math.PI) / 360)) * 0.9;
const DIAG = Math.atan2(W / 2, D / 2);
const VIEWS = [DIAG, Math.PI - DIAG, -(Math.PI - DIAG), -DIAG];
const NUDGE_AZ = 0.1, NUDGE_EL = 0.05, MOVE_MS = 900, SPRING_MS = 380;
const FREE_EL_MIN = (12 * Math.PI) / 180, FREE_EL_MAX = (40 * Math.PI) / 180;
const STUB = 0.07;
const SHIFT_MIN_WIDTH = 900;

interface ModeLook {
  hemi: number; hemiSky: string; hemiGround: string; sun: number; sunColor: string;
  fill: number; env: number; lamp: number; table: number; shade: number; glow: number;
  glass: string; glassEm: number; exposure: number; line: string; dim: string;
}

const MODES: Record<SampleRoomMode, ModeLook> = {
  day: {
    hemi: 1.05, hemiSky: "#eef3f8", hemiGround: "#8d7965", sun: 3.1, sunColor: "#fff0da",
    fill: 0.75, env: 0.3, lamp: 0, table: 0, shade: 0, glow: 0,
    glass: "#d6e6ef", glassEm: 0, exposure: 1.0, line: "#1b222b", dim: "#b8483a",
  },
  night: {
    hemi: 0.05, hemiSky: "#30425e", hemiGround: "#140f0b", sun: 0.42, sunColor: "#9fb6da",
    fill: 0.05, env: 0.035, lamp: 16, table: 6, shade: 2.2, glow: 1,
    glass: "#101c2e", glassEm: 0.55, exposure: 1.05, line: "#f4e9da", dim: "#ec9a86",
  },
};

function rng(seed: number): () => number {
  let s = seed >>> 0;
  return () => {
    s = (Math.imul(s, 1664525) + 1013904223) >>> 0;
    return s / 4294967296;
  };
}
const clamp01 = (t: number) => Math.min(Math.max(t, 0), 1);
const ease = (t: number) => 1 - Math.pow(1 - clamp01(t), 3);
const easeInOut = (t: number) => {
  const c = clamp01(t);
  return c < 0.5 ? 4 * c * c * c : 1 - Math.pow(-2 * c + 2, 3) / 2;
};
const wrap = (a: number) => {
  const t = Math.PI * 2;
  return ((a % t) + t) % t;
};
const shortestTurn = (a: number, b: number) => {
  const d = wrap(b - a);
  return d > Math.PI ? d - Math.PI * 2 : d;
};

interface Built {
  room: T.Group;
  floorGroup: T.Group;
  walls: Record<string, T.Group>;
  pieces: Record<string, T.Group>;
  glassMat: T.MeshStandardMaterial;
  lampLight: T.PointLight;
  lampShadeMat: T.MeshStandardMaterial;
  lampGlow: T.Sprite;
  tableLight: T.PointLight;
  tableShadeMat: T.MeshStandardMaterial;
  tableGlow: T.Sprite;
}

interface Shared {
  floorTex: T.Texture;
  artTex: T.Texture;
  shadowTex: T.Texture;
  glowTex: T.Texture;
}

function makeKit(lib: SampleRoomLib) {
  const { THREE, RoundedBoxGeometry } = lib;
  const mat = (color: number | string, opts: T.MeshStandardMaterialParameters = {}) =>
    new THREE.MeshStandardMaterial({ color, roughness: 0.86, metalness: 0, ...opts });
  const mesh = (geo: T.BufferGeometry, material: T.Material, shadows = true) => {
    const m = new THREE.Mesh(geo, material);
    m.castShadow = shadows;
    m.receiveShadow = true;
    return m;
  };
  const rbox = (w: number, h: number, d: number, r: number, material: T.Material, segs = 4) => {
    const rr = Math.max(0.001, Math.min(r, w / 2 - 0.001, h / 2 - 0.001, d / 2 - 0.001));
    return mesh(new RoundedBoxGeometry(w, h, d, segs, rr), material);
  };
  const box = (w: number, h: number, d: number, material: T.Material, shadows = true) =>
    mesh(new THREE.BoxGeometry(w, h, d), material, shadows);
  const cyl = (rt: number, rb: number, h: number, material: T.Material, seg = 40, open = false) =>
    mesh(new THREE.CylinderGeometry(rt, rb, h, seg, 1, open), material);
  const canvasTex = (
    w: number,
    h: number,
    draw: (g: CanvasRenderingContext2D, w: number, h: number) => void,
    srgb = true,
  ) => {
    const c = document.createElement("canvas");
    c.width = w;
    c.height = h;
    const g = c.getContext("2d");
    if (g) draw(g, w, h);
    const t = new THREE.CanvasTexture(c);
    if (srgb) t.colorSpace = THREE.SRGBColorSpace;
    return t;
  };
  return { mat, mesh, rbox, box, cyl, canvasTex };
}

type Kit = ReturnType<typeof makeKit>;

function makeShared(lib: SampleRoomLib, kit: Kit): Shared {
  const { THREE } = lib;
  const r = rng(11);
  const floorTex = kit.canvasTex(1024, 1024, (g) => {
    const rows = 12;
    const ph = 1024 / rows;
    g.fillStyle = "#c29e76";
    g.fillRect(0, 0, 1024, 1024);
    for (let row = 0; row < rows; row++) {
      let x = -r() * 520;
      while (x < 1024) {
        const len = (0.85 + r() * 1.05) * 512;
        const k = 1 + (r() - 0.5) * 0.12;
        g.fillStyle = `rgb(${Math.round(194 * k)},${Math.round(158 * k)},${Math.round(118 * k)})`;
        g.fillRect(x, row * ph, len, ph);
        for (let s = 0; s < 9; s++) {
          g.globalAlpha = 0.05 + r() * 0.06;
          g.fillStyle = r() > 0.5 ? "#7d5d3e" : "#e6c9a2";
          g.fillRect(x, row * ph + r() * ph, len, 1 + r() * 2.2);
        }
        g.globalAlpha = 1;
        g.fillStyle = "rgba(74,50,30,0.32)";
        g.fillRect(x, row * ph, 2, ph);
        x += len;
      }
      g.fillStyle = "rgba(74,50,30,0.38)";
      g.fillRect(0, row * ph, 1024, 1.6);
    }
  });
  floorTex.wrapS = floorTex.wrapT = THREE.RepeatWrapping;
  floorTex.repeat.set(W / 2, D / 2);
  floorTex.anisotropy = 8;
  const artTex = kit.canvasTex(400, 560, (g, w, h) => {
    g.fillStyle = "#e9e1d3";
    g.fillRect(0, 0, w, h);
    g.fillStyle = "#c04d3e";
    g.beginPath();
    g.arc(w * 0.5, h * 0.62, w * 0.3, Math.PI, 0);
    g.fill();
    g.fillStyle = "#26303b";
    g.fillRect(w * 0.2, h * 0.62, w * 0.6, 6);
    g.fillStyle = "#b9a98f";
    g.fillRect(w * 0.62, h * 0.18, w * 0.16, w * 0.16);
  });
  const shadowTex = kit.canvasTex(
    128,
    128,
    (g) => {
      const grd = g.createRadialGradient(64, 64, 0, 64, 64, 64);
      grd.addColorStop(0, "rgba(0,0,0,0.62)");
      grd.addColorStop(0.5, "rgba(0,0,0,0.3)");
      grd.addColorStop(1, "rgba(0,0,0,0)");
      g.fillStyle = grd;
      g.fillRect(0, 0, 128, 128);
    },
    false,
  );
  const glowTex = kit.canvasTex(128, 128, (g) => {
    const grd = g.createRadialGradient(64, 64, 0, 64, 64, 64);
    grd.addColorStop(0, "rgba(255,214,160,0.9)");
    grd.addColorStop(0.25, "rgba(255,180,105,0.35)");
    grd.addColorStop(1, "rgba(255,170,90,0)");
    g.fillStyle = grd;
    g.fillRect(0, 0, 128, 128);
  });
  return { floorTex, artTex, shadowTex, glowTex };
}

function buildRoom(lib: SampleRoomLib, kit: Kit, shared: Shared): Built {
  const { THREE } = lib;
  const { mat, mesh, rbox, box, cyl } = kit;
  const r = rng(5);
  const pieces: Record<string, T.Group> = {};
  const room = new THREE.Group();

  const floorGroup = new THREE.Group();
  const floor = mesh(new THREE.PlaneGeometry(W, D), mat(0xffffff, { map: shared.floorTex, roughness: 0.72 }), false);
  floor.rotation.x = -Math.PI / 2;
  // The plinth's top sits 6 mm under the floor: a shared plane would z-fight.
  const plinth = box(W + 2 * T_WALL + 0.06, 0.11, D + 2 * T_WALL + 0.06, mat(0xc9c6c1, { roughness: 0.9 }), false);
  plinth.position.y = -0.061;
  floorGroup.add(floor, plinth);
  room.add(floorGroup);

  const wallMat = mat(0xefebe5, { roughness: 0.95 });
  const pocheMat = mat(0x1b222b, { roughness: 0.6 });
  const trimMat = mat(0xf5f2ed, { roughness: 0.7 });
  const frameMat = mat(0xf7f5f1, { roughness: 0.5 });
  const oakTrim = mat(0xb88d5f, { roughness: 0.6 });

  const walls: Record<string, T.Group> = {};
  const makeWall = (name: string, normal: [number, number, number], point: [number, number, number]) => {
    const g = new THREE.Group();
    g.userData = { name, normal: new THREE.Vector3(...normal), point: new THREE.Vector3(...point), cut: 0 };
    walls[name] = g;
    room.add(g);
    return g;
  };
  const slab = (g: T.Group, x0: number, x1: number, y0: number, y1: number, z0: number, z1: number, material: T.Material = wallMat) => {
    const m = box(x1 - x0, y1 - y0, z1 - z0, material);
    m.position.set((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2);
    g.add(m);
    return m;
  };

  const back = makeWall("back", [0, 0, -1], [0, 1, Z0]);
  slab(back, X0 - T_WALL, WIN.x0, 0, H, Z0 - T_WALL, Z0);
  slab(back, WIN.x1, X1 + T_WALL, 0, H, Z0 - T_WALL, Z0);
  slab(back, WIN.x0, WIN.x1, 0, WIN.y0, Z0 - T_WALL, Z0);
  slab(back, WIN.x0, WIN.x1, WIN.y1, H, Z0 - T_WALL, Z0);
  slab(back, X0 - T_WALL, X1 + T_WALL, H, H + 0.008, Z0 - T_WALL - 0.001, Z0 + 0.001, pocheMat).castShadow = false;
  slab(back, X0, X1, 0, 0.075, Z0, Z0 + 0.014, trimMat);
  const fw = 0.05, fd = 0.08, fz0 = Z0 - T_WALL / 2 - fd / 2, fz1 = Z0 - T_WALL / 2 + fd / 2;
  slab(back, WIN.x0, WIN.x1, WIN.y0, WIN.y0 + fw, fz0, fz1, frameMat);
  slab(back, WIN.x0, WIN.x1, WIN.y1 - fw, WIN.y1, fz0, fz1, frameMat);
  slab(back, WIN.x0, WIN.x0 + fw, WIN.y0, WIN.y1, fz0, fz1, frameMat);
  slab(back, WIN.x1 - fw, WIN.x1, WIN.y0, WIN.y1, fz0, fz1, frameMat);
  const mx = (WIN.x0 + WIN.x1) / 2;
  slab(back, mx - 0.018, mx + 0.018, WIN.y0, WIN.y1, fz0, fz1, frameMat);
  slab(back, WIN.x0, WIN.x1, WIN.y1 - 0.44, WIN.y1 - 0.405, fz0, fz1, frameMat);
  const glassMat = new THREE.MeshStandardMaterial({
    color: 0xd6e6ef, roughness: 0.05, metalness: 0, transparent: true, opacity: 0.32,
    emissive: 0x101c2e, emissiveIntensity: 0, depthWrite: false,
  });
  const glass = new THREE.Mesh(new THREE.PlaneGeometry(WIN.x1 - WIN.x0, WIN.y1 - WIN.y0), glassMat);
  glass.position.set(mx, (WIN.y0 + WIN.y1) / 2, Z0 - T_WALL / 2);
  back.add(glass);
  slab(back, WIN.x0 - 0.06, WIN.x1 + 0.06, WIN.y0 - 0.03, WIN.y0, Z0 - 0.02, Z0 + 0.16, oakTrim);

  const front = makeWall("front", [0, 0, 1], [0, 1, Z1]);
  slab(front, X0 - T_WALL, X1 + T_WALL, 0, H, Z1, Z1 + T_WALL);
  slab(front, X0 - T_WALL, X1 + T_WALL, H, H + 0.008, Z1 - 0.001, Z1 + T_WALL + 0.001, pocheMat).castShadow = false;
  slab(front, X0, X1, 0, 0.075, Z1 - 0.014, Z1, trimMat);

  const left = makeWall("left", [-1, 0, 0], [X0, 1, 0]);
  slab(left, X0 - T_WALL, X0, 0, H, Z0, Z1);
  slab(left, X0 - T_WALL - 0.001, X0 + 0.001, H, H + 0.008, Z0, Z1, pocheMat).castShadow = false;
  slab(left, X0, X0 + 0.014, 0, 0.075, Z0, Z1, trimMat);

  const right = makeWall("right", [1, 0, 0], [X1, 1, 0]);
  slab(right, X1, X1 + T_WALL, 0, H, Z0, DOOR.z0);
  slab(right, X1, X1 + T_WALL, 0, H, DOOR.z1, Z1);
  slab(right, X1, X1 + T_WALL, DOOR.y1, H, DOOR.z0, DOOR.z1);
  slab(right, X1 - 0.001, X1 + T_WALL + 0.001, H, H + 0.008, Z0, Z1, pocheMat).castShadow = false;
  slab(right, X1 - 0.014, X1, 0, 0.075, Z0, DOOR.z0, trimMat);
  slab(right, X1 - 0.014, X1, 0, 0.075, DOOR.z1, Z1, trimMat);
  slab(right, X1 - 0.02, X1 + T_WALL + 0.02, 0, DOOR.y1 + 0.06, DOOR.z0 - 0.06, DOOR.z0, frameMat);
  slab(right, X1 - 0.02, X1 + T_WALL + 0.02, 0, DOOR.y1 + 0.06, DOOR.z1, DOOR.z1 + 0.06, frameMat);
  slab(right, X1 - 0.02, X1 + T_WALL + 0.02, DOOR.y1, DOOR.y1 + 0.06, DOOR.z0, DOOR.z1, frameMat);

  const contact = (x: number, z: number, w: number, d: number, y = 0.004, opacity = 0.55) => {
    const m = new THREE.Mesh(
      new THREE.PlaneGeometry(w, d),
      new THREE.MeshBasicMaterial({ map: shared.shadowTex, transparent: true, opacity, depthWrite: false }),
    );
    m.rotation.x = -Math.PI / 2;
    m.position.set(x, y, z);
    m.renderOrder = 1;
    m.userData.contact = true;
    return m;
  };
  const addPiece = (id: string, group: T.Group, size: number, wall: string | null = null) => {
    group.userData.id = id;
    group.userData.size = size;
    group.userData.wall = wall;
    pieces[id] = group;
    room.add(group);
    return group;
  };

  {
    const g = new THREE.Group();
    const rug = rbox(2.05, 0.014, 2.5, 0.006, mat(0xd9d0c2, { roughness: 1 }));
    rug.position.y = 0.007;
    const inner = box(1.85, 0.002, 2.3, mat(0xcfc4b3, { roughness: 1 }), false);
    inner.position.y = 0.0145;
    g.add(rug, inner);
    g.position.set(-0.55, 0, 0.1);
    addPiece("rug", g, 5.5);
  }

  {
    const g = new THREE.Group();
    const fabric = mat(0x5b6852, { roughness: 0.95 });
    const fabric2 = mat(0x67755d, { roughness: 0.95 });
    const legMat = mat(0x2a2420, { roughness: 0.5 });
    const L = 2.2;
    const base = rbox(0.9, 0.22, L, 0.05, fabric);
    base.position.set(0, 0.18, 0);
    g.add(base);
    for (const dz of [-0.627, 0, 0.627]) {
      const c = rbox(0.66, 0.15, 0.61, 0.065, fabric2);
      c.position.set(0.09, 0.362, dz);
      g.add(c);
      const bc = rbox(0.17, 0.4, 0.6, 0.075, fabric2);
      bc.position.set(-0.24, 0.62, dz);
      bc.rotation.z = -0.13;
      g.add(bc);
    }
    const backrest = rbox(0.2, 0.46, L, 0.07, fabric);
    backrest.position.set(-0.35, 0.52, 0);
    g.add(backrest);
    for (const s of [-1, 1]) {
      const arm = rbox(0.9, 0.52, 0.17, 0.07, fabric);
      arm.position.set(0, 0.33, s * (L / 2 - 0.085));
      g.add(arm);
    }
    for (const sx of [-0.4, 0.4]) {
      for (const sz of [-1.03, 1.03]) {
        const leg = cyl(0.022, 0.016, 0.07, legMat, 16);
        leg.position.set(sx, 0.035, sz);
        g.add(leg);
      }
    }
    const pillow = rbox(0.13, 0.34, 0.38, 0.06, mat(0xc0664b, { roughness: 0.95 }));
    pillow.position.set(-0.12, 0.55, 0.76);
    pillow.rotation.set(0.05, 0.25, -0.18);
    g.add(pillow);
    g.add(contact(0, 0, 1.25, 2.55, 0.017, 0.5));
    g.position.set(X0 + 0.47, 0, 0.0);
    addPiece("sofa", g, 4.2);
  }

  {
    const g = new THREE.Group();
    const wood = mat(0xf2eee8, { roughness: 0.75 });
    const Wd = 1.1, Hd = 1.1, Dd = 0.34;
    const sideL = box(0.025, Hd, Dd, wood);
    sideL.position.set(-Wd / 2 + 0.0125, Hd / 2, 0);
    const sideR = sideL.clone();
    sideR.position.x = Wd / 2 - 0.0125;
    const backP = box(Wd, Hd, 0.012, mat(0xe6e1d9));
    backP.position.set(0, Hd / 2, -Dd / 2 + 0.006);
    g.add(sideL, sideR, backP);
    const shelfY = [0.06, 0.56, 1.0875];
    for (const y of shelfY) {
      const s = box(y > 1 ? Wd : Wd - 0.05, 0.025, Dd, wood);
      s.position.set(0, y, 0);
      g.add(s);
    }
    const bookColors = [0x2f4a5c, 0xc0533f, 0xd8c6a2, 0x4f6a52, 0x8b9097, 0xe8e1d4, 0x6b4a3a, 0x1f2a36];
    for (let i = 0; i < 2; i++) {
      const y0 = shelfY[i] + 0.0125;
      let x = -Wd / 2 + 0.05;
      const end = Wd / 2 - 0.05;
      while (x < end - 0.05) {
        if (r() < 0.12) {
          x += 0.06 + r() * 0.1;
          continue;
        }
        const bw = 0.025 + r() * 0.03;
        const bh = 0.2 + r() * 0.13;
        const bd = 0.19 + r() * 0.05;
        if (x + bw > end) break;
        const b = box(bw, bh, bd, mat(bookColors[Math.floor(r() * bookColors.length)], { roughness: 0.8 }));
        b.position.set(x + bw / 2, y0 + bh / 2, 0.02);
        g.add(b);
        x += bw + 0.003;
      }
    }
    const vase = cyl(0.06, 0.045, 0.24, mat(0x3b4a5a, { roughness: 0.4 }), 24);
    vase.position.set(0.3, 1.22, 0.02);
    const books = box(0.24, 0.05, 0.18, mat(0xc0533f, { roughness: 0.8 }));
    books.position.set(-0.28, 1.125, 0.02);
    const books2 = box(0.2, 0.04, 0.16, mat(0xe8e1d4, { roughness: 0.8 }));
    books2.position.set(-0.27, 1.17, 0.02);
    books2.rotation.y = 0.15;
    g.add(vase, books, books2);
    g.add(contact(0, 0.02, 1.4, 0.62, 0.004, 0.45));
    g.position.set(-0.75, 0, Z0 + Dd / 2 + 0.005);
    addPiece("shelf", g, 3.5);
  }

  {
    const g = new THREE.Group();
    const fabric = mat(0xa8583f, { roughness: 0.95 });
    const legMat = mat(0x6e4a32, { roughness: 0.6 });
    const base = rbox(0.82, 0.24, 0.8, 0.06, fabric);
    base.position.set(0, 0.19, 0);
    const seat = rbox(0.56, 0.13, 0.6, 0.06, mat(0xb4644a, { roughness: 0.95 }));
    seat.position.set(0, 0.37, 0.05);
    const backR = rbox(0.82, 0.5, 0.18, 0.08, fabric);
    backR.position.set(0, 0.6, -0.33);
    backR.rotation.x = -0.12;
    g.add(base, seat, backR);
    for (const s of [-1, 1]) {
      const arm = rbox(0.14, 0.44, 0.8, 0.06, fabric);
      arm.position.set(s * 0.34, 0.29, 0);
      g.add(arm);
    }
    for (const sx of [-0.33, 0.33]) {
      for (const sz of [-0.32, 0.32]) {
        const leg = cyl(0.02, 0.014, 0.07, legMat, 12);
        leg.position.set(sx, 0.035, sz);
        g.add(leg);
      }
    }
    g.add(contact(0, 0, 1.15, 1.12, 0.017, 0.5));
    g.position.set(1.0, 0, 0.38);
    g.rotation.y = -Math.PI / 2 - 0.42;
    addPiece("armchair", g, 3.0);
  }

  {
    const g = new THREE.Group();
    const oak = mat(0xb48a5d, { roughness: 0.55 });
    const metal = mat(0x23262b, { roughness: 0.4, metalness: 0.3 });
    const top = rbox(0.58, 0.035, 1.1, 0.012, oak);
    top.position.y = 0.4;
    g.add(top);
    for (const sx of [-0.25, 0.25]) {
      for (const sz of [-0.5, 0.5]) {
        const leg = box(0.022, 0.385, 0.022, metal);
        leg.position.set(sx, 0.19, sz);
        g.add(leg);
      }
    }
    const b1 = box(0.22, 0.03, 0.28, mat(0x2f4a5c));
    b1.position.set(0.05, 0.433, -0.22);
    const b2 = box(0.19, 0.025, 0.24, mat(0xe8e1d4));
    b2.position.set(0.04, 0.46, -0.21);
    b2.rotation.y = 0.2;
    const bowl = mesh(
      new THREE.SphereGeometry(0.09, 32, 16, 0, Math.PI * 2, Math.PI / 2, Math.PI / 2),
      mat(0xc04d3e, { roughness: 0.4, side: THREE.DoubleSide }),
    );
    bowl.rotation.x = Math.PI;
    bowl.position.set(-0.02, 0.508, 0.26);
    bowl.scale.y = 0.55;
    g.add(b1, b2, bowl);
    g.add(contact(0, 0, 0.85, 1.35, 0.018, 0.38));
    g.position.set(-0.6, 0, 0.0);
    addPiece("table", g, 2.0);
  }

  {
    const g = new THREE.Group();
    const oak = mat(0xa97f53, { roughness: 0.55 });
    const body = rbox(1.5, 0.52, 0.42, 0.015, oak);
    body.position.y = 0.36;
    g.add(body);
    for (const sx of [-0.7, 0.7]) {
      for (const sz of [-0.17, 0.17]) {
        const leg = box(0.03, 0.1, 0.03, mat(0x23262b, { roughness: 0.4 }));
        leg.position.set(sx, 0.05, sz);
        g.add(leg);
      }
    }
    for (const sx of [-0.375, 0.375]) {
      const door = box(0.72, 0.44, 0.004, mat(0xb68c5e, { roughness: 0.5 }));
      door.position.set(sx, 0.36, -0.212);
      g.add(door);
    }
    const jar = cyl(0.07, 0.09, 0.26, mat(0xe8e1d4, { roughness: 0.4 }), 32);
    jar.position.set(-0.45, 0.75, 0);
    const stack = box(0.26, 0.06, 0.2, mat(0xc0533f));
    stack.position.set(0.3, 0.65, 0);
    const stack2 = box(0.22, 0.05, 0.18, mat(0x2f4a5c));
    stack2.position.set(0.31, 0.705, 0.01);
    g.add(jar, stack, stack2);
    g.add(contact(0, 0, 1.8, 0.7, 0.004, 0.42));
    g.position.set(0.15, 0, Z1 - 0.23);
    addPiece("sideboard", g, 2.2);
  }

  let lampLight!: T.PointLight;
  let lampShadeMat!: T.MeshStandardMaterial;
  let lampGlow!: T.Sprite;
  {
    const g = new THREE.Group();
    const metal = mat(0x1d2025, { roughness: 0.35, metalness: 0.4 });
    const base = cyl(0.15, 0.16, 0.025, metal);
    base.position.y = 0.0125;
    const stem = cyl(0.011, 0.011, 1.5, metal, 12);
    stem.position.y = 0.77;
    lampShadeMat = mat(0xf2e9da, { roughness: 0.9, emissive: 0xffbe7a, emissiveIntensity: 0, side: THREE.DoubleSide });
    const shade = cyl(0.17, 0.23, 0.32, lampShadeMat, 48, true);
    shade.castShadow = false;
    shade.position.y = 1.62;
    g.add(base, stem, shade);
    lampLight = new THREE.PointLight(0xffb066, 0, 0, 2);
    lampLight.position.set(0, 1.56, 0);
    lampLight.castShadow = true;
    lampLight.shadow.mapSize.set(1024, 1024);
    lampLight.shadow.bias = -0.002;
    lampLight.shadow.radius = 6;
    g.add(lampLight);
    lampGlow = new THREE.Sprite(
      new THREE.SpriteMaterial({ map: shared.glowTex, transparent: true, opacity: 0, depthWrite: false, blending: THREE.AdditiveBlending }),
    );
    lampGlow.position.set(0, 1.6, 0);
    lampGlow.scale.set(1.3, 1.3, 1);
    g.add(lampGlow);
    g.add(contact(0, 0, 0.5, 0.5, 0.004, 0.45));
    g.position.set(X0 + 0.38, 0, Z0 + 0.4);
    addPiece("lamp", g, 1.4);
  }

  {
    const g = new THREE.Group();
    const pot = cyl(0.17, 0.13, 0.36, mat(0xb5654b, { roughness: 0.8 }), 40);
    pot.position.y = 0.18;
    const soil = cyl(0.155, 0.155, 0.01, mat(0x3a2b20), 32);
    soil.position.y = 0.34;
    const stem = cyl(0.012, 0.016, 0.95, mat(0x5a4632), 8);
    stem.position.y = 0.8;
    g.add(pot, soil, stem);
    const leafGeo = new THREE.SphereGeometry(1, 16, 10);
    const greens = [0x4b6a44, 0x5b7c51, 0x3f5c3b, 0x6a8a5c];
    for (let i = 0; i < 34; i++) {
      const y = 0.5 + i * 0.024 + r() * 0.04;
      const a = i * 2.39996;
      const rad = 0.05 + r() * 0.06;
      const leaf = mesh(leafGeo, mat(greens[i % greens.length], { roughness: 0.7 }));
      leaf.scale.set(0.15 + r() * 0.05, 0.011, 0.085 + r() * 0.02);
      leaf.position.set(Math.cos(a) * (rad + 0.1), y, Math.sin(a) * (rad + 0.1));
      leaf.rotation.set(0, -a, 0.35 + r() * 0.4);
      g.add(leaf);
    }
    g.add(contact(0, 0, 0.6, 0.6, 0.004, 0.45));
    g.position.set(X1 - 0.38, 0, Z0 + 0.42);
    addPiece("plant", g, 1.2);
  }

  let tableLight!: T.PointLight;
  let tableShadeMat!: T.MeshStandardMaterial;
  let tableGlow!: T.Sprite;
  {
    const g = new THREE.Group();
    const oak = mat(0xa97f53, { roughness: 0.55 });
    const top = cyl(0.23, 0.23, 0.03, oak, 48);
    top.position.y = 0.52;
    const ped = cyl(0.03, 0.03, 0.5, mat(0x23262b, { roughness: 0.4 }), 16);
    ped.position.y = 0.26;
    const foot = cyl(0.15, 0.16, 0.02, mat(0x23262b, { roughness: 0.4 }), 32);
    foot.position.y = 0.01;
    const lb = mesh(new THREE.SphereGeometry(0.08, 32, 16), mat(0xe7e1d6, { roughness: 0.35 }));
    lb.position.set(0.04, 0.6, 0);
    lb.scale.y = 1.1;
    tableShadeMat = mat(0xf2e9da, { roughness: 0.9, emissive: 0xffbe7a, emissiveIntensity: 0, side: THREE.DoubleSide });
    const sh = cyl(0.1, 0.14, 0.16, tableShadeMat, 40, true);
    sh.castShadow = false;
    sh.position.set(0.04, 0.78, 0);
    g.add(top, ped, foot, lb, sh);
    tableLight = new THREE.PointLight(0xffaa5e, 0, 0, 2);
    tableLight.position.set(0.04, 0.76, 0);
    g.add(tableLight);
    tableGlow = new THREE.Sprite(
      new THREE.SpriteMaterial({ map: shared.glowTex, transparent: true, opacity: 0, depthWrite: false, blending: THREE.AdditiveBlending }),
    );
    tableGlow.position.set(0.04, 0.78, 0);
    tableGlow.scale.set(0.8, 0.8, 1);
    g.add(tableGlow);
    g.add(contact(0, 0, 0.6, 0.6, 0.004, 0.42));
    g.position.set(X0 + 0.42, 0, Z1 - 0.38);
    addPiece("sidetable", g, 1.0);
  }

  {
    const g = new THREE.Group();
    const frame = box(0.035, 0.82, 0.62, mat(0x24282e, { roughness: 0.5 }));
    const art = new THREE.Mesh(new THREE.PlaneGeometry(0.54, 0.74), mat(0xffffff, { map: shared.artTex, roughness: 0.9 }));
    art.rotation.y = Math.PI / 2;
    art.position.x = 0.019;
    g.add(frame, art);
    g.position.set(X0 + 0.02, 1.55, 0.0);
    addPiece("art", g, 0.6, "left");
  }

  {
    const g = new THREE.Group();
    const linen = mat(0xe9e3d8, { roughness: 1 });
    for (const x of [WIN.x0 - 0.2, WIN.x1 + 0.2]) {
      for (let k = 0; k < 4; k++) {
        const fold = cyl(0.045, 0.05, 2.42, linen, 16);
        fold.position.set(x - 0.12 + k * 0.08, 1.21, Z0 + 0.1 + (k % 2) * 0.02);
        g.add(fold);
      }
    }
    const rod = cyl(0.012, 0.012, WIN.x1 - WIN.x0 + 0.9, mat(0x23262b, { roughness: 0.4 }), 12);
    rod.rotation.z = Math.PI / 2;
    rod.position.set(mx, 2.43, Z0 + 0.11);
    g.add(rod);
    addPiece("curtains", g, 0.8, "back");
  }

  return { room, floorGroup, walls, pieces, glassMat, lampLight, lampShadeMat, lampGlow, tableLight, tableShadeMat, tableGlow };
}

interface Dim {
  wall: string;
  text: string;
  at: [number, number];
  group: T.Group;
  material: T.MeshBasicMaterial;
  sprite: T.Sprite | null;
}

interface Anim {
  from: number;
  to: number;
  start: number;
  dur: number;
}

/** Mount the sample room on a canvas. Rendering pauses while the canvas is
 * off screen; `dispose` releases the GPU resources. */
export function mountSampleRoom(lib: SampleRoomLib, canvas: HTMLCanvasElement, options: SampleRoomOptions = {}): SampleRoomHandle {
  const { THREE, OrbitControls, RoomEnvironment } = lib;
  const o = {
    mode: "day" as SampleRoomMode, stage: "furnished" as SampleRoomStage, reveal: false, interactive: true,
    labels: true, removed: [] as string[], free: false, view: 0, fit: 1, shift: 0, ...options,
  };
  const kit = makeKit(lib);
  const shared = makeShared(lib, kit);

  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.setClearColor(0x000000, 0);

  const scene = new THREE.Scene();
  const pmrem = new THREE.PMREMGenerator(renderer);
  const envTexture = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
  scene.environment = envTexture;

  const built = buildRoom(lib, kit, shared);
  scene.add(built.room);
  const wallList = Object.values(built.walls);

  const lineMat = new THREE.MeshBasicMaterial({ color: MODES[o.mode].line, transparent: true, opacity: 1, depthWrite: false });
  const footMat = new THREE.MeshBasicMaterial({ color: MODES[o.mode].line, transparent: true, opacity: 0.75, depthWrite: false });
  const strip = (len: number, width: number, material: T.Material) => {
    const m = new THREE.Mesh(new THREE.PlaneGeometry(len, width), material);
    m.rotation.x = -Math.PI / 2;
    return m;
  };

  // The measured outline, drawn edge by edge during the reveal.
  const outline = new THREE.Group();
  const outlineParts: T.Group[] = [];
  for (const [ax, az, bx, bz] of [
    [X0, Z1, X1, Z1],
    [X1, Z1, X1, Z0],
    [X1, Z0, X0, Z0],
    [X0, Z0, X0, Z1],
  ]) {
    const len = Math.hypot(bx - ax, bz - az);
    const pivot = new THREE.Group();
    pivot.position.set(ax, 0.022, az);
    pivot.rotation.y = -Math.atan2(bz - az, bx - ax);
    const s = strip(len, 0.03, lineMat);
    s.position.x = len / 2;
    const holder = new THREE.Group();
    holder.add(s);
    pivot.add(holder);
    outline.add(pivot);
    outlineParts.push(holder);
  }
  scene.add(outline);

  // One dimension line per wall, outside the plinth; shown on the cut side.
  const OFF = T_WALL + 0.38;
  const dims: Dim[] = (
    [
      { wall: "front", a: [X0, Z1 + OFF], b: [X1, Z1 + OFF], text: "4.40 m", at: [0, Z1 + OFF + 0.3] },
      { wall: "back", a: [X0, Z0 - OFF], b: [X1, Z0 - OFF], text: "4.40 m", at: [0, Z0 - OFF - 0.3] },
      { wall: "right", a: [X1 + OFF, Z0], b: [X1 + OFF, Z1], text: "3.60 m", at: [X1 + OFF + 0.42, 0] },
      { wall: "left", a: [X0 - OFF, Z0], b: [X0 - OFF, Z1], text: "3.60 m", at: [X0 - OFF - 0.42, 0] },
    ] as const
  ).map((d) => {
    const material = new THREE.MeshBasicMaterial({ color: MODES[o.mode].dim, transparent: true, opacity: 0, depthWrite: false });
    const group = new THREE.Group();
    const [ax, az] = d.a;
    const [bx, bz] = d.b;
    const len = Math.hypot(bx - ax, bz - az);
    const pivot = new THREE.Group();
    pivot.position.set(ax, -0.1, az);
    pivot.rotation.y = -Math.atan2(bz - az, bx - ax);
    const s = strip(len, 0.016, material);
    s.position.x = len / 2;
    pivot.add(s);
    for (const tx of [0, len]) {
      const tick = strip(0.016, 0.16, material);
      tick.position.x = tx;
      pivot.add(tick);
    }
    group.add(pivot);
    scene.add(group);
    return { wall: d.wall, text: d.text, at: [d.at[0], d.at[1]] as [number, number], group, material, sprite: null };
  });

  const state = { mode: o.mode, t: o.mode === "night" ? 1 : 0, tFrom: 0, tTo: 0, tStart: -1 };

  const makeLabels = () => {
    const color = MODES[state.mode].dim;
    for (const d of dims) {
      if (d.sprite) {
        d.group.remove(d.sprite);
        d.sprite.material.map?.dispose();
        d.sprite.material.dispose();
      }
      d.sprite = null;
      if (!o.labels) continue;
      const font = '500 54px "JetBrains Mono", ui-monospace, Menlo, monospace';
      const probe = document.createElement("canvas").getContext("2d");
      if (!probe) continue;
      probe.font = font;
      const w = Math.ceil(probe.measureText(d.text).width) + 36;
      const tex = kit.canvasTex(w, 84, (g) => {
        g.font = font;
        g.fillStyle = color;
        g.textBaseline = "middle";
        g.fillText(d.text, 18, 44);
      });
      const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, opacity: 0, depthTest: false, depthWrite: false }));
      s.scale.set((0.2 * w) / 84, 0.2, 1);
      s.position.set(d.at[0], -0.02, d.at[1]);
      s.renderOrder = 20;
      d.group.add(s);
      d.sprite = s;
    }
  };

  const hemi = new THREE.HemisphereLight(0xffffff, 0x000000, 1);
  scene.add(hemi);
  const sun = new THREE.DirectionalLight(0xffffff, 1);
  sun.position.set(2.6, 5.2, -6.5);
  sun.target.position.set(0.7, 0, 0.6);
  sun.castShadow = true;
  sun.shadow.mapSize.set(2048, 2048);
  Object.assign(sun.shadow.camera, { left: -5, right: 5, top: 5, bottom: -5, near: 1, far: 20 });
  sun.shadow.bias = -0.0004;
  sun.shadow.normalBias = 0.02;
  sun.shadow.radius = 3;
  scene.add(sun, sun.target);
  const fill = new THREE.DirectionalLight(0xfff6ee, 1);
  fill.position.set(6, 7.5, 7);
  fill.castShadow = true;
  fill.shadow.mapSize.set(2048, 2048);
  Object.assign(fill.shadow.camera, { left: -5, right: 5, top: 5, bottom: -5, near: 1, far: 25 });
  fill.shadow.bias = -0.0004;
  fill.shadow.normalBias = 0.02;
  fill.shadow.radius = 8;
  scene.add(fill);

  const camera = new THREE.PerspectiveCamera(FOV, 1, 1, 60);
  const target = new THREE.Vector3(0, H * 0.45, 0);
  let dist = BASE_DIST;
  const controls: OrbitControlsT = new OrbitControls(camera, canvas);
  controls.enableZoom = false;
  controls.enablePan = false;
  controls.rotateSpeed = 0.5;
  controls.target.copy(target);
  controls.enabled = o.interactive;

  const startView = Math.max(0, Math.min(VIEW_COUNT - 1, Math.round(o.view)));
  const rig = {
    free: o.free,
    index: startView,
    move: null as null | { t0: number; ms: number; az0: number; el0: number; az1: number; el1: number },
    az: VIEWS[startView],
    el: ELEV,
  };
  let needsRender = true;
  const place = (az: number, el: number) => {
    rig.az = az;
    rig.el = el;
    camera.position.set(
      target.x + Math.sin(az) * Math.cos(el) * dist,
      target.y + Math.sin(el) * dist,
      target.z + Math.cos(az) * Math.cos(el) * dist,
    );
    camera.lookAt(target);
  };
  const clearLimits = () => {
    controls.minAzimuthAngle = -Infinity;
    controls.maxAzimuthAngle = Infinity;
    controls.minPolarAngle = 0;
    controls.maxPolarAngle = Math.PI;
  };
  const freeLimits = () => {
    clearLimits();
    controls.minPolarAngle = Math.PI / 2 - FREE_EL_MAX;
    controls.maxPolarAngle = Math.PI / 2 - FREE_EL_MIN;
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
  };
  const viewLimits = (i: number) => {
    const az = VIEWS[i];
    if (Math.abs(az) + NUDGE_AZ < Math.PI) {
      controls.minAzimuthAngle = az - NUDGE_AZ;
      controls.maxAzimuthAngle = az + NUDGE_AZ;
    } else {
      controls.minAzimuthAngle = -Infinity;
      controls.maxAzimuthAngle = Infinity;
    }
    controls.minPolarAngle = Math.PI / 2 - ELEV - NUDGE_EL;
    controls.maxPolarAngle = Math.PI / 2 - ELEV + NUDGE_EL;
    controls.enableDamping = false;
  };
  const notify = () => o.onView?.(rig.free ? -1 : rig.index);
  const startMove = (az1: number, el1: number, ms: number) => {
    clearLimits();
    controls.enabled = false;
    rig.move = { t0: performance.now(), ms, az0: rig.az, el0: rig.el, az1, el1 };
    needsRender = true;
  };
  const goTo = (i: number) => {
    rig.free = false;
    rig.index = ((Math.round(i) % VIEW_COUNT) + VIEW_COUNT) % VIEW_COUNT;
    startMove(VIEWS[rig.index], ELEV, MOVE_MS);
    notify();
  };
  const sphe = new THREE.Spherical();
  controls.addEventListener("change", () => {
    needsRender = true;
    sphe.setFromVector3(camera.position.clone().sub(target));
    rig.az = sphe.theta;
    rig.el = Math.PI / 2 - sphe.phi;
  });
  controls.addEventListener("end", () => {
    if (rig.free || rig.move) return;
    const daz = Math.abs(shortestTurn(rig.az, VIEWS[rig.index]));
    const del = Math.abs(rig.el - ELEV);
    if (daz + del > 0.004) startMove(VIEWS[rig.index], ELEV, SPRING_MS);
  });

  const resize = () => {
    const w = canvas.clientWidth || 800;
    const h = canvas.clientHeight || 500;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    const tan = Math.tan((FOV * Math.PI) / 360);
    const shiftOn = o.shift !== 0 && w >= SHIFT_MIN_WIDTH;
    const usable = shiftOn ? 1 - Math.abs(o.shift) * 1.6 : 1;
    const needW = (RADIUS + 0.45) / (tan * camera.aspect * Math.max(0.35, usable));
    dist = Math.max(BASE_DIST, needW * 0.92) / o.fit;
    // Near and far hug the room: depth precision is what keeps thin slabs
    // from z-fighting at this distance (the product's rig does the same).
    camera.near = Math.max(0.5, dist - RADIUS * 1.9);
    camera.far = dist + RADIUS * 3;
    if (shiftOn) camera.setViewOffset(w, h, -o.shift * w, 0, w, h);
    else camera.clearViewOffset();
    camera.updateProjectionMatrix();
    controls.minDistance = controls.maxDistance = dist;
    place(rig.az, rig.el);
    controls.update();
    needsRender = true;
  };

  if (rig.free) freeLimits();
  else viewLimits(rig.index);

  const sec = () => performance.now() / 1000;
  const pieceList = Object.values(built.pieces).sort((a, b) => b.userData.size - a.userData.size);
  for (const g of pieceList) {
    g.userData.baseY = g.position.y;
    g.userData.p = 1;
    g.userData.anim = null;
    g.traverse((m) => {
      const mm = m as T.Mesh;
      if (mm.isMesh && mm.material && !Array.isArray(mm.material) && !mm.material.userData.cloned) {
        mm.material = mm.material.clone();
        mm.material.userData.cloned = true;
        mm.material.userData.baseOpacity = mm.material.opacity;
        mm.material.userData.baseTransparent = mm.material.transparent;
      }
    });
  }
  const pieceAlpha = (g: T.Group) => {
    const wall = g.userData.wall ? built.walls[g.userData.wall as string] : null;
    return wall ? 1 - easeInOut(wall.userData.cut as number) : 1;
  };
  const applyPiece = (g: T.Group) => {
    const p = g.userData.p as number;
    const e = ease(p);
    const wa = pieceAlpha(g);
    g.position.y = (g.userData.baseY as number) + (1 - e) * 0.55;
    g.visible = p > 0.001 && wa > 0.01;
    const k = Math.min(1, e * 1.4) * wa;
    const full = p >= 0.999 && wa >= 0.999;
    g.traverse((m) => {
      const mm = m as T.Mesh;
      if (mm.isMesh && mm.material && !Array.isArray(mm.material)) {
        const base = mm.material.userData;
        mm.material.transparent = full ? (base.baseTransparent as boolean) : true;
        mm.material.opacity = ((base.baseOpacity as number) ?? 1) * k;
        mm.material.depthWrite = full ? !(base.baseTransparent as boolean) : k > 0.6;
      }
    });
  };
  const animatePiece = (g: T.Group, to: number, delay = 0, dur = 0.75) => {
    g.userData.anim = { from: g.userData.p, to, start: sec() + delay, dur } satisfies Anim;
  };

  const shell = {
    floor: 1, walls: 1, line: 1,
    floorAnim: null as Anim | null, wallAnim: null as Anim | null, lineAnim: null as Anim | null,
  };
  let stageNow: SampleRoomStage = o.stage;
  const removed = new Set(o.removed);

  const applyShell = () => {
    const fe = ease(shell.floor);
    built.floorGroup.visible = shell.floor > 0.001;
    built.floorGroup.traverse((m) => {
      const mm = m as T.Mesh;
      if (mm.isMesh && !Array.isArray(mm.material)) {
        mm.material.transparent = shell.floor < 0.999;
        mm.material.opacity = fe;
      }
    });
    const rise = easeInOut(shell.walls);
    for (const wall of wallList) {
      const cutScale = 1 - (1 - STUB / H) * easeInOut(wall.userData.cut as number);
      wall.visible = shell.walls > 0.001;
      wall.scale.y = Math.max(0.001, rise * cutScale);
    }
    const n = outlineParts.length;
    outlineParts.forEach((holder, i) => {
      const local = clamp01(shell.line * n - i);
      holder.scale.x = Math.max(0.0001, easeInOut(local));
      holder.visible = local > 0.0001;
    });
    lineMat.opacity = stageNow === "furnished" ? 0 : 1;
    for (const d of dims) {
      const a = (o.labels ? 1 : 0) * easeInOut(built.walls[d.wall].userData.cut as number) * clamp01(shell.line * 1.2);
      d.material.opacity = a * 0.9;
      d.group.visible = a > 0.01;
      if (d.sprite) d.sprite.material.opacity = a;
    }
  };

  // The guest's "taken out" proposal leaves the piece's place marked.
  const footprints = new THREE.Group();
  scene.add(footprints);
  const drawFootprint = (g: T.Group) => {
    const inv = new THREE.Matrix4().makeRotationY(-g.rotation.y);
    const saveY = g.position.y;
    g.position.y = g.userData.baseY as number;
    g.updateMatrixWorld(true);
    const pts: T.Vector3[] = [];
    const origin = new THREE.Vector3(g.position.x, 0, g.position.z);
    g.traverse((m) => {
      const mm = m as T.Mesh;
      if (mm.isMesh && mm.geometry && !mm.userData.contact) {
        mm.geometry.computeBoundingBox();
        const gb = mm.geometry.boundingBox;
        if (!gb) return;
        for (const x of [gb.min.x, gb.max.x]) {
          for (const z of [gb.min.z, gb.max.z]) {
            pts.push(new THREE.Vector3(x, 0, z).applyMatrix4(mm.matrixWorld).sub(origin).applyMatrix4(inv));
          }
        }
      }
    });
    g.position.y = saveY;
    const local = new THREE.Box3().setFromPoints(pts);
    const size = new THREE.Vector3();
    local.getSize(size);
    const cx = (local.min.x + local.max.x) / 2;
    const cz = (local.min.z + local.max.z) / 2;
    const grp = new THREE.Group();
    const dash = 0.09, gap = 0.06, wdt = 0.022;
    const edge = (x0: number, z0: number, x1: number, z1: number) => {
      const len = Math.hypot(x1 - x0, z1 - z0);
      const ang = Math.atan2(z1 - z0, x1 - x0);
      for (let s = 0; s < len; s += dash + gap) {
        const l = Math.min(dash, len - s);
        const m = strip(l, wdt, footMat);
        const holder = new THREE.Group();
        holder.rotation.y = -ang;
        holder.position.set(x0, 0, z0);
        m.position.x = s + l / 2;
        holder.add(m);
        grp.add(holder);
      }
    };
    const hx = size.x / 2, hz = size.z / 2;
    edge(cx - hx, cz - hz, cx + hx, cz - hz);
    edge(cx + hx, cz - hz, cx + hx, cz + hz);
    edge(cx + hx, cz + hz, cx - hx, cz + hz);
    edge(cx - hx, cz + hz, cx - hx, cz - hz);
    grp.rotation.y = g.rotation.y;
    grp.position.set(g.position.x, 0.03, g.position.z);
    grp.userData.forId = g.userData.id;
    footprints.add(grp);
  };

  const setRemoved = (ids: string[]) => {
    const next = new Set(ids);
    for (const g of pieceList) {
      const want = next.has(g.userData.id as string) ? 0 : stageNow === "furnished" ? 1 : 0;
      animatePiece(g, want, 0, 0.7);
    }
    for (const f of [...footprints.children]) if (!next.has(f.userData.forId as string)) footprints.remove(f);
    for (const id of next) {
      if (!footprints.children.some((f) => f.userData.forId === id) && built.pieces[id]) drawFootprint(built.pieces[id]);
    }
    removed.clear();
    for (const id of next) removed.add(id);
    needsRender = true;
  };

  const setStage = (s: SampleRoomStage, animate = true) => {
    stageNow = s;
    const tShell = s === "outline" ? 0 : 1;
    const tFloor = s === "outline" ? 0.35 : 1;
    if (animate) {
      shell.lineAnim = { from: shell.line, to: 1, start: sec(), dur: 1.1 };
      shell.floorAnim = { from: shell.floor, to: tFloor, start: sec() + (s === "outline" ? 0 : 0.5), dur: 0.8 };
      shell.wallAnim = { from: shell.walls, to: tShell, start: sec() + (s === "outline" ? 0 : 0.9), dur: 1.0 };
    } else {
      shell.line = 1;
      shell.floor = tFloor;
      shell.walls = tShell;
    }
    const furnish = s === "furnished";
    let k = 0;
    for (const g of pieceList) {
      const want = furnish && !removed.has(g.userData.id as string) ? 1 : 0;
      if (animate) {
        animatePiece(g, want, want ? 1.9 + k * 0.16 : 0, want ? 0.8 : 0.45);
        if (want) k++;
      } else {
        g.userData.p = want;
        applyPiece(g);
      }
    }
    footprints.visible = furnish;
    applyShell();
    needsRender = true;
  };

  const replay = (to?: SampleRoomStage) => {
    if (to) stageNow = to;
    shell.line = 0;
    shell.floor = 0;
    shell.walls = 0;
    for (const g of pieceList) {
      g.userData.p = 0;
      applyPiece(g);
    }
    applyShell();
    setStage(stageNow, true);
  };

  const applyMode = (t: number) => {
    const a = MODES.day, b = MODES.night;
    const lerp = (x: number, y: number) => x + (y - x) * t;
    const lerpC = (x: string, y: string) => new THREE.Color(x).lerp(new THREE.Color(y), t);
    hemi.intensity = lerp(a.hemi, b.hemi);
    hemi.color.copy(lerpC(a.hemiSky, b.hemiSky));
    hemi.groundColor.copy(lerpC(a.hemiGround, b.hemiGround));
    sun.intensity = lerp(a.sun, b.sun);
    sun.color.copy(lerpC(a.sunColor, b.sunColor));
    fill.intensity = lerp(a.fill, b.fill);
    scene.environmentIntensity = lerp(a.env, b.env);
    built.lampLight.intensity = lerp(a.lamp, b.lamp);
    built.tableLight.intensity = lerp(a.table, b.table);
    built.lampShadeMat.emissiveIntensity = lerp(a.shade, b.shade);
    built.tableShadeMat.emissiveIntensity = lerp(a.shade, b.shade) * 0.9;
    built.lampGlow.material.opacity = lerp(a.glow, b.glow) * 0.9;
    built.tableGlow.material.opacity = lerp(a.glow, b.glow) * 0.75;
    built.glassMat.color.copy(lerpC(a.glass, b.glass));
    built.glassMat.emissiveIntensity = lerp(a.glassEm, b.glassEm);
    renderer.toneMappingExposure = lerp(a.exposure, b.exposure);
    lineMat.color.copy(lerpC(a.line, b.line));
    footMat.color.copy(lerpC(a.line, b.line));
    for (const d of dims) d.material.color.copy(lerpC(a.dim, b.dim));
    built.lampLight.castShadow = t > 0.05;
  };
  const setMode = (m: SampleRoomMode) => {
    if (m === state.mode) return;
    state.mode = m;
    state.tFrom = state.t;
    state.tTo = m === "night" ? 1 : 0;
    state.tStart = sec();
    makeLabels();
    needsRender = true;
  };

  // Cutaway: the walls between the camera and the room come down to stubs.
  let lastCut = sec();
  const updateCutaway = (instant = false) => {
    let moving = false;
    const t = sec();
    const stepAmt = Math.min(1, (t - lastCut) / 0.35);
    lastCut = t;
    for (const wall of wallList) {
      const v = camera.position.clone().sub(wall.userData.point as T.Vector3);
      const want = v.dot(wall.userData.normal as T.Vector3) > 0.05 ? 1 : 0;
      const c = wall.userData.cut as number;
      if (instant) wall.userData.cut = want;
      else if (Math.abs(c - want) > 0.001) {
        wall.userData.cut = c + Math.sign(want - c) * Math.min(Math.abs(want - c), stepAmt);
        moving = true;
      } else wall.userData.cut = want;
    }
    return moving;
  };

  applyMode(state.t);
  for (const g of pieceList) g.userData.p = o.stage === "furnished" && !removed.has(g.userData.id as string) ? 1 : 0;
  for (const id of removed) if (built.pieces[id]) drawFootprint(built.pieces[id]);
  footprints.visible = o.stage === "furnished";
  shell.line = 1;
  shell.floor = o.stage === "outline" ? 0.35 : 1;
  shell.walls = o.stage === "outline" ? 0 : 1;
  if (o.reveal) {
    shell.line = 0;
    shell.floor = 0;
    shell.walls = 0;
    for (const g of pieceList) g.userData.p = 0;
  }

  const ro = new ResizeObserver(() => resize());
  ro.observe(canvas);
  resize();
  updateCutaway(true);
  for (const g of pieceList) applyPiece(g);
  applyShell();

  let visible = true;
  let revealed = !o.reveal;
  const startReveal = () => {
    if (revealed) return;
    revealed = true;
    window.setTimeout(() => setStage(stageNow, true), 200);
  };
  const io = new IntersectionObserver(
    (entries) => {
      for (const e of entries) {
        visible = e.isIntersecting;
        if (visible) {
          needsRender = true;
          if (e.intersectionRatio > 0.2) startReveal();
        }
      }
    },
    { threshold: [0, 0.25, 0.5] },
  );
  io.observe(canvas);

  const step = (anim: Anim | null, apply: (v: number) => void): Anim | null => {
    if (!anim) return null;
    const tt = sec();
    if (tt < anim.start) return anim;
    const k = Math.min(1, (tt - anim.start) / anim.dur);
    apply(anim.from + (anim.to - anim.from) * k);
    return k >= 1 ? null : anim;
  };

  let raf = 0;
  let disposed = false;
  const loop = () => {
    if (disposed) return;
    raf = requestAnimationFrame(loop);
    if (!visible) return;
    let busy = false;

    if (state.tStart >= 0) {
      const k = Math.min(1, (sec() - state.tStart) / 1.1);
      state.t = state.tFrom + (state.tTo - state.tFrom) * easeInOut(k);
      applyMode(state.t);
      if (k >= 1) state.tStart = -1;
      busy = true;
    }

    if (rig.move) {
      const m = rig.move;
      const k = Math.min(1, (performance.now() - m.t0) / m.ms);
      const e = easeInOut(k);
      place(m.az0 + shortestTurn(m.az0, m.az1) * e, m.el0 + (m.el1 - m.el0) * e);
      if (k >= 1) {
        rig.move = null;
        controls.enabled = o.interactive;
        controls.update();
        if (rig.free) freeLimits();
        else viewLimits(rig.index);
      }
      busy = true;
    } else if (controls.update()) {
      busy = true;
    }

    if (updateCutaway()) busy = true;

    shell.lineAnim = step(shell.lineAnim, (v) => {
      shell.line = v;
    });
    shell.floorAnim = step(shell.floorAnim, (v) => {
      shell.floor = v;
    });
    shell.wallAnim = step(shell.wallAnim, (v) => {
      shell.walls = v;
    });
    if (shell.lineAnim || shell.floorAnim || shell.wallAnim) busy = true;
    applyShell();

    for (const g of pieceList) {
      if (g.userData.anim) {
        g.userData.anim = step(g.userData.anim as Anim, (v) => {
          g.userData.p = v;
        });
        busy = true;
      }
      applyPiece(g);
    }

    if (busy || needsRender) {
      renderer.render(scene, camera);
      needsRender = false;
    }
  };
  loop();

  makeLabels();
  document.fonts?.ready.then(() => {
    if (disposed) return;
    makeLabels();
    applyShell();
    needsRender = true;
  });

  return {
    setMode,
    setStage: (s) => setStage(s, true),
    setRemoved,
    replay,
    goTo,
    dispose() {
      disposed = true;
      cancelAnimationFrame(raf);
      io.disconnect();
      ro.disconnect();
      controls.dispose();
      envTexture.dispose();
      pmrem.dispose();
      scene.traverse((m) => {
        const mm = m as T.Mesh;
        if (mm.isMesh) {
          mm.geometry?.dispose();
          if (!Array.isArray(mm.material)) mm.material?.dispose();
        }
      });
      for (const t of Object.values(shared)) t.dispose();
      renderer.dispose();
    },
  };
}
