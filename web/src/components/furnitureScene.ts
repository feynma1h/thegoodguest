/**
 * Builds the furniture twins (lib/furniture.ts) into three.js groups:
 * rounded, softly lit, procedurally textured pieces in the finished room's
 * light. Everything is DRAWN from the spec's numbers — no photo pixels, no
 * splats. Takes the three.js module (and the RoundedBoxGeometry addon) as
 * arguments so the renderer library stays imported in one place (decision
 * 0053), like shellFinishScene.
 */

import type * as THREE_NS from "three";

import { RIG_COMP, roomEnvironment } from "@/components/shellFinishScene";
import { DEFAULT_EXPOSURE, type ShellFinish } from "@/lib/shellFinish";
import type { FurnitureBundle, FurnitureSpec, MatSpec, Part, TexSpec, Vec3 } from "@/lib/furniture";

type T = typeof THREE_NS;
type RoundedBox = new (w: number, h: number, d: number, seg?: number, r?: number) => THREE_NS.BufferGeometry;

function rng(seed: number) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function canvas(w: number, h: number) {
  const c = document.createElement("canvas");
  c.width = w;
  c.height = h;
  return { c, ctx: c.getContext("2d")! };
}

// ---------------------------------------------------------------- textures --
/** A bare winter tree: recursive forking branches (a motif of the quilt texture's cells). */
function drawTree(ctx: CanvasRenderingContext2D, x: number, y: number, s: number, r: () => number, color: string, blossom: string | null) {
  ctx.strokeStyle = color;
  ctx.lineCap = "round";
  const branch = (bx: number, by: number, ang: number, len: number, depth: number) => {
    const ex = bx + Math.cos(ang) * len;
    const ey = by + Math.sin(ang) * len;
    ctx.lineWidth = Math.max(0.6, s * 0.03 * (depth / 5));
    ctx.beginPath();
    ctx.moveTo(bx, by);
    ctx.lineTo(ex, ey);
    ctx.stroke();
    if (depth <= 0) {
      if (blossom && r() > 0.5) {
        ctx.fillStyle = blossom;
        ctx.beginPath();
        ctx.arc(ex, ey, s * 0.016, 0, Math.PI * 2);
        ctx.fill();
      }
      return;
    }
    const n = depth > 3 ? 2 : 3;
    for (let i = 0; i < n; i++) branch(ex, ey, ang + (i - (n - 1) / 2) * (0.5 + 0.25 * r()), len * (0.68 + 0.12 * r()), depth - 1);
  };
  branch(x + s * 0.5, y + s * 1.0, -Math.PI / 2 + (r() - 0.5) * 0.15, s * 0.3, 5);
}

function quiltCell(ctx: CanvasRenderingContext2D, x: number, y: number, s: number, kind: number, pal: string[], r: () => number) {
  // pal: navy, slate blue, pale blue, cream, tan, brown, teal
  const [navy, blue, pale, cream, tan, brown, teal] = pal;
  const fill = (c: string) => {
    ctx.fillStyle = c;
    ctx.fillRect(x, y, s, s);
  };
  const dots = (n: number, c: string, rad: number) => {
    ctx.fillStyle = c;
    for (let i = 0; i < n; i++) {
      ctx.beginPath();
      ctx.arc(x + r() * s, y + r() * s, rad, 0, Math.PI * 2);
      ctx.fill();
    }
  };
  switch (kind) {
    case 0: // arched-window disc: white ring, tan/navy slats, on a pale or tan ground
    case 6: {
      fill(kind === 0 ? pale : tan);
      const cx = x + s / 2;
      const cy = y + s / 2;
      ctx.fillStyle = cream;
      ctx.beginPath();
      ctx.arc(cx, cy, s * 0.41, 0, Math.PI * 2);
      ctx.fill();
      ctx.save();
      ctx.beginPath();
      ctx.arc(cx, cy, s * 0.35, 0, Math.PI * 2);
      ctx.clip();
      ctx.fillStyle = cream;
      ctx.fillRect(x, y, s, s);
      for (let i = 0; i < 5; i++) {
        ctx.fillStyle = i % 2 ? tan : navy;
        ctx.fillRect(x, y + s * (0.2 + i * 0.12), s, s * 0.075);
      }
      ctx.restore();
      break;
    }
    case 1: { // bare tree on tan with a few white blossoms
      fill(tan);
      drawTree(ctx, x, y, s, r, brown, "rgba(250,246,236,0.9)");
      break;
    }
    case 2: { // navy half disc on a pale ground
      fill(pale);
      ctx.fillStyle = navy;
      ctx.beginPath();
      ctx.arc(x + s / 2, y + s * 0.82, s * 0.4, Math.PI, 0);
      ctx.fill();
      dots(30, "rgba(200,212,230,0.35)", s * 0.01);
      break;
    }
    case 3: { // dark teal-slate square with a fine pale lace of diamonds
      fill(teal);
      ctx.fillStyle = "rgba(190,205,225,0.55)";
      for (let i = 0; i < 9; i++)
        for (let j = 0; j < 9; j++) {
          const cx = x + s * (0.1 + i * 0.1);
          const cy = y + s * (0.1 + j * 0.1);
          if ((i + j) % 2 === 0) {
            ctx.beginPath();
            ctx.moveTo(cx, cy - s * 0.035);
            ctx.lineTo(cx + s * 0.035, cy);
            ctx.lineTo(cx, cy + s * 0.035);
            ctx.lineTo(cx - s * 0.035, cy);
            ctx.fill();
          }
        }
      ctx.strokeStyle = pale;
      ctx.lineWidth = s * 0.02;
      ctx.strokeRect(x + s * 0.05, y + s * 0.05, s * 0.9, s * 0.9);
      break;
    }
    case 4: { // pinstripe band: cream and pale blue with a fine chain line
      fill(cream);
      ctx.fillStyle = pale;
      for (let i = 0; i < 7; i++) ctx.fillRect(x, y + s * (0.04 + i * 0.14), s, s * 0.07);
      ctx.fillStyle = blue;
      for (let i = 0; i < 3; i++) ctx.fillRect(x, y + s * (0.22 + i * 0.28), s, s * 0.018);
      break;
    }
    default: { // dark tree on a cream ground
      fill(cream);
      drawTree(ctx, x, y, s, r, "rgba(70,72,90,0.85)", null);
    }
  }
  // Faint seam between patchwork cells.
  ctx.strokeStyle = "rgba(90,90,100,0.12)";
  ctx.lineWidth = Math.max(1, s * 0.01);
  ctx.strokeRect(x, y, s, s);
}

function makeTexture(THREE: T, t: TexSpec, base: string): { map: THREE_NS.Texture; tileM: number } {
  const r = rng(t.seed ?? 7);
  const pal = t.palette ?? [];
  const p = t.p ?? {};
  let size = 512;
  let tileM = t.tile_m ?? 1;
  let draw: (ctx: CanvasRenderingContext2D) => void;
  if (t.kind === "quilt") {
    const n = p.cells ?? 6;
    size = 1024;
    tileM = t.tile_m ?? n * (p.cell_m ?? 0.14);
    draw = (ctx) => {
      const s = size / n;
      let last = -1;
      for (let j = 0; j < n; j++)
        for (let i = 0; i < n; i++) {
          let k = Math.floor(r() * 7);
          if (k === last) k = (k + 1) % 7;
          last = k;
          quiltCell(ctx, i * s, j * s, s, k, pal, r);
        }
    };
  } else if (t.kind === "wood") {
    draw = (ctx) => {
      ctx.fillStyle = base;
      ctx.fillRect(0, 0, size, size);
      const contrast = p.contrast ?? 0.22;
      for (let i = 0; i < 260; i++) {
        const y = r() * size;
        const light = r() > 0.5;
        ctx.strokeStyle = light ? `rgba(255,235,200,${contrast * 0.5 * r()})` : `rgba(20,8,0,${contrast * r()})`;
        ctx.lineWidth = 0.6 + r() * 2.2;
        ctx.beginPath();
        ctx.moveTo(0, y);
        const wob = 2 + r() * 6;
        for (let x = 0; x <= size; x += 64) ctx.lineTo(x, y + Math.sin(x / 90 + i) * wob);
        ctx.stroke();
      }
    };
  } else if (t.kind === "weave") {
    size = 256;
    tileM = t.tile_m ?? 0.12;
    draw = (ctx) => {
      ctx.fillStyle = base;
      ctx.fillRect(0, 0, size, size);
      const k = p.contrast ?? 0.07;
      for (let y = 0; y < size; y += 2) {
        ctx.fillStyle = `rgba(0,0,0,${k})`;
        ctx.fillRect(0, y, size, 1);
      }
      for (let x = 0; x < size; x += 2) {
        ctx.fillStyle = `rgba(255,255,255,${k})`;
        ctx.fillRect(x, 0, 1, size);
      }
      for (let i = 0; i < 3000; i++) {
        ctx.fillStyle = `rgba(${r() > 0.5 ? "255,255,255" : "0,0,0"},${0.05 * r()})`;
        ctx.fillRect(r() * size, r() * size, 2, 2);
      }
    };
  } else if (t.kind === "lattice") {
    size = 512;
    tileM = t.tile_m ?? 0.26;
    const [bg, line, hi] = [pal[0] ?? base, pal[1] ?? "#fff", pal[2] ?? "#fff"];
    draw = (ctx) => {
      ctx.fillStyle = bg;
      ctx.fillRect(0, 0, size, size);
      const n = p.n ?? 2;
      const R = size / n / 2;
      for (const [w, c] of [[R * 0.34, line], [R * 0.09, hi]] as [number, string][]) {
        ctx.strokeStyle = c;
        ctx.lineWidth = w;
        for (let j = -1; j <= n; j++)
          for (let i = -1; i <= n; i++) {
            ctx.beginPath();
            ctx.ellipse(i * R * 2 + R, j * R * 2 + R, R * 1.0, R * 1.35, 0, 0, Math.PI * 2);
            ctx.stroke();
          }
      }
    };
  } else if (t.kind === "ribbon") {
    // Interlocking wavy white ribbons over a field of triangles in three blues
    // (a printed cloth): palette = [deep, mid, light, ribbon white].
    size = 512;
    tileM = t.tile_m ?? 0.42;
    const [deep, mid, light, white] = [pal[0] ?? "#14306e", pal[1] ?? "#2d63b8", pal[2] ?? "#6fa3dc", pal[3] ?? "#e6ebf3"];
    draw = (ctx) => {
      const n = p.n ?? 3;
      const s = size / n;
      const cols = [deep, deep, mid, light, mid, deep];
      for (let j = 0; j < n; j++)
        for (let i = 0; i < n; i++) {
          const flip = (i + j) % 2 === 0;
          const a: [number, number][] = flip ? [[0, 0], [s, 0], [s, s]] : [[s, 0], [s, s], [0, s]];
          const b: [number, number][] = flip ? [[0, 0], [s, s], [0, s]] : [[0, 0], [s, 0], [0, s]];
          for (const tri of [a, b]) {
            ctx.fillStyle = cols[Math.floor(r() * cols.length)];
            ctx.beginPath();
            ctx.moveTo(i * s + tri[0][0], j * s + tri[0][1]);
            ctx.lineTo(i * s + tri[1][0], j * s + tri[1][1]);
            ctx.lineTo(i * s + tri[2][0], j * s + tri[2][1]);
            ctx.closePath();
            ctx.fill();
          }
        }
      // Two families of wavy diagonal ribbons, periodic across the tile.
      const wave = (dir: 1 | -1, w: number, c: string) => {
        ctx.strokeStyle = c;
        ctx.lineWidth = w;
        ctx.lineCap = "round";
        for (let k = -n; k <= n; k++) {
          ctx.beginPath();
          for (let u = -s; u <= size + s; u += 6) {
            const off = Math.sin((u / size) * Math.PI * 2 * n) * s * 0.3;
            const x = u;
            const y = dir * u + k * s + off;
            if (u === -s) ctx.moveTo(x, dir === 1 ? y : size - y);
            else ctx.lineTo(x, dir === 1 ? y : size - y);
          }
          ctx.stroke();
        }
      };
      wave(1, size / 30, white);
      wave(-1, size / 30, white);
    };
  } else if (t.kind === "stripe") {
    draw = (ctx) => {
      const n = p.n ?? 8;
      const w = size / n;
      for (let i = 0; i < n; i++) {
        ctx.fillStyle = pal[i % Math.max(pal.length, 1)] ?? base;
        if (p.vertical === 0) ctx.fillRect(0, i * w, size, w);
        else ctx.fillRect(i * w, 0, w, size);
      }
    };
  } else {
    draw = (ctx) => {
      ctx.fillStyle = base;
      ctx.fillRect(0, 0, size, size);
      ctx.strokeStyle = pal[0] ?? "rgba(0,0,0,0.3)";
      ctx.lineWidth = p.line ?? 3;
      const n = p.n ?? 4;
      for (let i = 0; i <= n; i++) {
        ctx.beginPath();
        ctx.moveTo((i * size) / n, 0);
        ctx.lineTo((i * size) / n, size);
        ctx.moveTo(0, (i * size) / n);
        ctx.lineTo(size, (i * size) / n);
        ctx.stroke();
      }
    };
  }
  const { c, ctx } = canvas(size, size);
  draw(ctx);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
  tex.anisotropy = 8;
  return { map: tex, tileM };
}

// -------------------------------------------------------------- geometries --
/** Box-project uv in metres: the face's dominant normal axis picks the
 * plane, so a texture tile always covers `tileM` metres whatever the part's
 * size. */
function metreUV(THREE: T, geom: THREE_NS.BufferGeometry, tileM: number, swap: boolean) {
  const pos = geom.getAttribute("position");
  const nor = geom.getAttribute("normal");
  const uv = new Float32Array(pos.count * 2);
  for (let i = 0; i < pos.count; i++) {
    const nx = Math.abs(nor.getX(i));
    const ny = Math.abs(nor.getY(i));
    const nz = Math.abs(nor.getZ(i));
    let u: number;
    let v: number;
    if (ny >= nx && ny >= nz) {
      u = pos.getX(i);
      v = pos.getZ(i);
    } else if (nx >= nz) {
      u = pos.getZ(i);
      v = pos.getY(i);
    } else {
      u = pos.getX(i);
      v = pos.getY(i);
    }
    uv[i * 2] = (swap ? v : u) / tileM;
    uv[i * 2 + 1] = (swap ? u : v) / tileM;
  }
  geom.setAttribute("uv", new THREE.BufferAttribute(uv, 2));
}

function partGeometry(THREE: T, RBG: RoundedBox, part: Part): THREE_NS.BufferGeometry {
  switch (part.kind) {
    case "box": {
      const [w, h, d] = part.size;
      const r = Math.min(part.bevel ?? 0.006, Math.min(w, h, d) / 2 - 1e-4);
      return r > 0.0005 ? new RBG(w, h, d, 4, r) : new THREE.BoxGeometry(w, h, d);
    }
    case "cyl":
      return new THREE.CylinderGeometry(part.rTop ?? part.r, part.r, part.h, part.seg ?? 32);
    case "sphere": {
      const g = new THREE.SphereGeometry(1, 40, 24);
      const [a, b, c] = typeof part.r === "number" ? [part.r, part.r, part.r] : part.r;
      g.scale(a, b, c);
      return g;
    }
    case "lathe":
      return new THREE.LatheGeometry(part.profile.map(([r, y]) => new THREE.Vector2(r, y)), part.seg ?? 40);
    case "tube": {
      const curve = new THREE.CatmullRomCurve3(part.path.map((p) => new THREE.Vector3(...p)), part.closed ?? false);
      return new THREE.TubeGeometry(curve, Math.max(24, part.path.length * 14), part.r, 14, part.closed ?? false);
    }
    case "extrude": {
      const shape = new THREE.Shape(part.outline.map(([x, y]) => new THREE.Vector2(x, y)));
      const b = part.bevel ?? 0.006;
      const g = new THREE.ExtrudeGeometry(shape, {
        depth: Math.max(part.depth - 2 * b, 0.001),
        bevelEnabled: b > 0,
        bevelSize: b,
        bevelThickness: b,
        bevelSegments: 3,
        curveSegments: 16,
      });
      g.translate(0, 0, -(part.depth - 2 * b) / 2);
      return g;
    }
    case "books":
      return new THREE.BufferGeometry(); // built per book in buildFurniture
    case "drape": {
      const seg = Math.max(part.folds * 12, 24);
      const g = new THREE.PlaneGeometry(part.w, part.h, seg, 8);
      const pos = g.getAttribute("position");
      for (let i = 0; i < pos.count; i++) {
        const x = pos.getX(i);
        // Pleats are deeper near the hem than the gathered head.
        const hemK = 0.55 + 0.45 * (1 - (pos.getY(i) + part.h / 2 + (part.hemOff ?? 0)) / (part.hemH ?? part.h));
        pos.setZ(i, part.amp * hemK * Math.sin((x / part.w) * Math.PI * 2 * part.folds));
      }
      g.computeVertexNormals();
      return g;
    }
  }
}

export interface ModeParams {
  day: { sun: number; ambient: number; hemi: number; key: number; radius: number };
  night: { moon: number; lamp: number; ambient: number; hemi: number; key: number; exposure: number };
}

// ---------------------------------------------------------------- builder --
export type RoomMode = "day" | "night";

export interface BuiltFurniture {
  root: THREE_NS.Group;
  /** Day: window light, faint shadows. Night: the part named lamp-shade lights the room. */
  mode: () => RoomMode;
  setMode: (m: RoomMode) => void;
  /** Live-tunable light levels for the two modes (call setMode(mode()) after editing). */
  params: ModeParams;
  /** Per frame: hide wall-mounted twins whose wall the camera sees from outside (the cutaway). */
  update: (camera: THREE_NS.Camera) => void;
  byKey: Record<string, THREE_NS.Group>;
  dispose: () => void;
}

export function buildFurniture(
  THREE: T,
  RBG: RoundedBox,
  scene: THREE_NS.Scene,
  bundle: FurnitureBundle,
  finish: ShellFinish | null,
  renderer: THREE_NS.WebGLRenderer,
  floorMesh: THREE_NS.Mesh | null,
  opts: { domParent?: HTMLElement | null; onChange?: () => void } = {},
): BuiltFurniture {
  const exposure = finish?.exposure ?? DEFAULT_EXPOSURE;
  const diorama = bundle.look !== "photo";
  // The diorama look pulls every colour a little toward the muted, warm-neutral
  // range of the reference renders (hue kept, saturation eased) so the room
  // reads as one designed palette; the photo look leaves colours as measured.
  const soft = (hex: string): string => {
    if (!diorama) return hex;
    const col = new THREE.Color(hex);
    const hsl = { h: 0, s: 0, l: 0 };
    col.getHSL(hsl);
    col.setHSL(hsl.h, hsl.s * 0.78, hsl.l);
    return `#${col.getHexString()}`;
  };
  // FURN_K: furniture sits a touch darker than the shell under the same rig
  // (measured as render-vs-photo dL on a bed over three frames); one calibrated constant.
  const FURN_K = 0.8;
  const gain = new THREE.Color().setRGB(exposure * RIG_COMP[0] * FURN_K, exposure * RIG_COMP[1] * FURN_K, exposure * RIG_COMP[2] * FURN_K);
  const envRt = finish ? roomEnvironment(THREE, renderer, finish) : null;
  const disposables: Array<{ dispose(): void }> = envRt ? [envRt] : [];

  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  if (floorMesh) {
    floorMesh.receiveShadow = true;
    (floorMesh.material as THREE_NS.Material).needsUpdate = true;
  }

  const root = new THREE.Group();
  root.name = "furniture-twins";
  const walled: { g: THREE_NS.Group; nx: number; nz: number }[] = [];
  const byKey: Record<string, THREE_NS.Group> = {};
  const bounds = new THREE.Box3();

  const makeMaterial = (m: MatSpec): { mat: THREE_NS.Material; tileM: number } => {
    let tileM = 1;
    const base = new THREE.Color(soft(m.color));
    const params: THREE_NS.MeshPhysicalMaterialParameters = {
      color: base.clone().multiply(gain),
      roughness: m.rough ?? 0.7,
      metalness: m.metal ?? 0,
      envMap: envRt?.texture ?? null,
      envMapIntensity: (m.rough ?? 0.7) < 0.5 ? 0.9 : 0.35,
      side: m.double ? THREE.DoubleSide : THREE.FrontSide,
    };
    if (m.clearcoat) {
      params.clearcoat = m.clearcoat;
      params.clearcoatRoughness = 0.18;
    }
    if (m.opacity !== undefined && m.opacity < 1) {
      params.transparent = true;
      params.opacity = m.opacity;
      params.depthWrite = false;
    }
    if (m.emissive) {
      params.emissive = new THREE.Color(m.emissive);
      params.emissiveIntensity = m.emissive_intensity ?? 1;
    }
    const mat = new THREE.MeshPhysicalMaterial(params);
    if (m.tex) {
      const tex = { ...m.tex, palette: m.tex.palette?.map(soft) };
      const { map, tileM: tm } = makeTexture(THREE, tex, soft(m.color));
      tileM = tm;
      mat.map = map;
      // The painted texture already carries its colours; the gain alone tints it.
      mat.color = gain.clone();
      if (m.tex.kind === "wood" || m.tex.kind === "weave" || m.bump) {
        mat.bumpMap = map;
        mat.bumpScale = (m.bump ?? 0.4) * 0.8;
      }
      disposables.push(map);
    }
    disposables.push(mat);
    return { mat, tileM };
  };

  for (const placed of bundle.objects) {
    const spec: FurnitureSpec = placed.spec;
    const mats: Record<string, THREE_NS.Material> = {};
    const tileOf: Record<string, number> = {};
    for (const [name, ms] of Object.entries(spec.materials)) {
      const made = makeMaterial(ms);
      mats[name] = made.mat;
      tileOf[name] = made.tileM;
    }
    const g = new THREE.Group();
    g.name = spec.key;
    g.position.set(...placed.position);
    g.rotation.y = placed.yaw;
    for (const part of spec.parts) {
      const mat = mats[part.mat];
      if (!mat) throw new Error(`furniture ${spec.key}: part uses unknown material ${part.mat}`);
      if (part.kind === "books") {
        const r = rng(part.seed ?? 1);
        let x = -part.w / 2;
        let i = 0;
        while (x < part.w / 2 - 0.02) {
          const t = (part.tmin ?? 0.025) + r() * ((part.tmax ?? 0.05) - (part.tmin ?? 0.025));
          const h = part.hmin + r() * (part.hmax - part.hmin);
          const d = part.depth * (0.85 + 0.15 * r());
          const bm = mats[part.mats[i % part.mats.length]] ?? mat;
          const bg = new RBG(t, h, d, 2, Math.min(0.004, t / 3));
          metreUV(THREE, bg, 1, false);
          const bk = new THREE.Mesh(bg, bm);
          const at = part.at ?? [0, 0, 0];
          bk.position.set(at[0] + x + t / 2, at[1] + h / 2, at[2]);
          bk.rotation.z = (r() - 0.5) * (r() > 0.85 ? 0.35 : 0.04);
          bk.castShadow = true;
          bk.receiveShadow = true;
          bk.name = "book";
          g.add(bk);
          disposables.push(bg);
          x += t + 0.002;
          i += 1 + Math.floor(r() * 2);
        }
        continue;
      }
      const geom = partGeometry(THREE, RBG, part);
      metreUV(THREE, geom, tileOf[part.mat], part.uvSwap ?? false);
      const mesh = new THREE.Mesh(geom, mat);
      if (part.at) mesh.position.set(...part.at);
      if (part.rot) mesh.rotation.set(...(part.rot.map((d) => (d * Math.PI) / 180) as Vec3));
      mesh.castShadow = !part.noShadow && !(mat as THREE_NS.MeshPhysicalMaterial).transparent;
      mesh.receiveShadow = true;
      mesh.name = part.name ?? part.kind;
      g.add(mesh);
      disposables.push(geom);
    }
    // A soft contact shadow under the piece, on top of the real one.
    const [bw, , bd] = spec.box_dims;
    const { c, ctx } = canvas(128, 128);
    const grd = ctx.createRadialGradient(64, 64, 8, 64, 64, 64);
    grd.addColorStop(0, "rgba(40,36,30,0.34)");
    grd.addColorStop(0.6, "rgba(40,36,30,0.16)");
    grd.addColorStop(1, "rgba(40,36,30,0)");
    ctx.fillStyle = grd;
    ctx.fillRect(0, 0, 128, 128);
    const blobTex = new THREE.CanvasTexture(c);
    const blob = new THREE.Mesh(
      new THREE.PlaneGeometry(bw * 1.3, bd * 1.3),
      new THREE.MeshBasicMaterial({ map: blobTex, transparent: true, depthWrite: false, toneMapped: false }),
    );
    blob.name = "contact-shadow";
    blob.rotation.x = -Math.PI / 2;
    blob.position.y = 0.004;
    blob.renderOrder = 1;
    g.add(blob);
    disposables.push(blobTex, blob.geometry, blob.material as THREE_NS.Material);
    root.add(g);
    byKey[spec.key] = g;
    if (placed.mount === "wall") walled.push({ g, nx: Math.sin(placed.yaw), nz: Math.cos(placed.yaw) });
  }
  scene.add(root);
  bounds.setFromObject(root);

  // The key light. In the photo look it is the weak sun the render-vs-photo loop
  // was calibrated with. In the diorama look it is a warm window light: it comes
  // in through the window wall (the wall a twin of category "window" is in) and throws the
  // long soft shadows that sit the pieces on the floor and show the room's depth;
  // the shell's flat hemisphere wash is turned down so the light has something
  // to shape.
  const c = bounds.getCenter(new THREE.Vector3());
  const windows = bundle.objects.filter((o) => o.category === "window");
  const inward = windows.length ? new THREE.Vector3(Math.sin(windows[0].yaw), 0, Math.cos(windows[0].yaw)) : new THREE.Vector3(0.6, 0, 0.8);
  const sun = new THREE.DirectionalLight(0xfff1e0, diorama ? 2.6 : 0.3);
  if (diorama) {
    sun.color.set(0xffe9cf);
    // Low, from outside the window wall (30 degrees): long shadows that run away from the window.
    sun.position.set(c.x - inward.x * 7.8, c.y + 4.5, c.z - inward.z * 7.8);
  } else {
    sun.position.set(c.x + 2.2, c.y + 5.5, c.z + 1.6);
  }
  sun.target.position.copy(c);
  sun.castShadow = true;
  sun.shadow.mapSize.set(2048, 2048);
  const cam = sun.shadow.camera;
  cam.left = cam.bottom = -6;
  cam.right = cam.top = 6;
  cam.near = 0.5;
  cam.far = 22;
  sun.shadow.radius = diorama ? 12 : 7;
  sun.shadow.bias = -0.0004;
  sun.shadow.normalBias = 0.02;
  scene.add(sun, sun.target);

  const restore: Array<() => void> = [];
  // The shell's own rig (ambient, hemisphere wash, an unshadowed key) is bright and flat;
  // each mode sets how much of it stays so the window light or the lamp has something to shape.
  const shellLights: { l: THREE_NS.Light; was: number; color: THREE_NS.Color }[] = [];
  scene.traverse((o) => {
    const l = o as THREE_NS.Light;
    if (l.isLight && l !== sun) shellLights.push({ l, was: l.intensity, color: l.color.clone() });
  });
  restore.push(() => shellLights.forEach((s) => { s.l.intensity = s.was; s.l.color.copy(s.color); }));
  if (diorama) {
    // Walls, plinth and floor catch the furniture's shadow too.
    const underRoot = (o: THREE_NS.Object3D) => {
      for (let p: THREE_NS.Object3D | null = o; p; p = p.parent) if (p === root) return true;
      return false;
    };
    scene.traverse((o) => {
      const m = o as THREE_NS.Mesh;
      if (m.isMesh && !underRoot(m) && !m.receiveShadow && (m.material as THREE_NS.MeshStandardMaterial)?.isMeshStandardMaterial) {
        m.receiveShadow = true;
        restore.push(() => (m.receiveShadow = false));
      }
    });
    // Corner occlusion: a soft dark gradient on the floor along every wall foot.
    if (floorMesh) {
      const pos = floorMesh.geometry.getAttribute("position");
      const pts: THREE_NS.Vector3[] = [];
      for (let i = 0; i < pos.count; i++) {
        const v = new THREE.Vector3().fromBufferAttribute(pos, i).applyMatrix4(floorMesh.matrixWorld);
        if (!pts.some((q) => q.distanceTo(v) < 1e-3)) pts.push(v);
      }
      const ctr = pts.reduce((a, b) => a.add(b), new THREE.Vector3()).multiplyScalar(1 / pts.length);
      pts.sort((a, b) => Math.atan2(a.z - ctr.z, a.x - ctr.x) - Math.atan2(b.z - ctr.z, b.x - ctr.x));
      const { c: gc, ctx: gx } = canvas(8, 128);
      const gg = gx.createLinearGradient(0, 0, 0, 128);
      gg.addColorStop(0, "rgba(46,38,30,0.42)");
      gg.addColorStop(0.35, "rgba(46,38,30,0.16)");
      gg.addColorStop(1, "rgba(46,38,30,0)");
      gx.fillStyle = gg;
      gx.fillRect(0, 0, 8, 128);
      const aoTex = new THREE.CanvasTexture(gc);
      const aoMat = new THREE.MeshBasicMaterial({ map: aoTex, transparent: true, depthWrite: false, toneMapped: false, polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2 });
      const fy = Math.min(...pts.map((p) => p.y)) + 0.003;
      const W = 0.55;
      const aoGroup = new THREE.Group();
      aoGroup.name = "corner-ao";
      for (let i = 0; i < pts.length; i++) {
        const a = pts[i];
        const b = pts[(i + 1) % pts.length];
        const e = b.clone().sub(a).setY(0);
        const inw = new THREE.Vector3(-e.z, 0, e.x).normalize();
        if (inw.dot(ctr.clone().sub(a).setY(0)) < 0) inw.negate();
        const g = new THREE.BufferGeometry();
        const a2 = a.clone().addScaledVector(inw, W);
        const b2 = b.clone().addScaledVector(inw, W);
        g.setAttribute("position", new THREE.Float32BufferAttribute([a.x, fy, a.z, b.x, fy, b.z, b2.x, fy, b2.z, a2.x, fy, a2.z], 3));
        g.setAttribute("uv", new THREE.Float32BufferAttribute([0, 1, 1, 1, 1, 0, 0, 0], 2));
        g.setIndex([0, 2, 1, 0, 3, 2, 0, 1, 2, 0, 2, 3]);
        const strip = new THREE.Mesh(g, aoMat);
        strip.renderOrder = 1;
        aoGroup.add(strip);
        disposables.push(g);
      }
      scene.add(aoGroup);
      disposables.push(aoTex, aoMat);
      restore.push(() => scene.remove(aoGroup));
    }
  }



  // ---- Day and night (diorama look only) ----------------------------------------------
  const params: ModeParams = {
    day: { sun: 2.2, ambient: 0.6, hemi: 0.58, key: 0.5, radius: 12 },
    night: { moon: 0.25, lamp: 5, ambient: 0.12, hemi: 0.14, key: 0.08, exposure: 1.0 },
  };
  root.updateMatrixWorld(true);
  const lampMesh = ((): THREE_NS.Object3D | null => {
    let found: THREE_NS.Object3D | null = null;
    root.traverse((o) => { if (!found && o.name === "lamp-shade") found = o; });
    return found;
  })();
  const lampLight = new THREE.PointLight(0xffc477, 0, 0, 0.9);
  if (lampMesh) {
    const lp = new THREE.Vector3();
    (lampMesh as THREE_NS.Object3D).getWorldPosition(lp);
    lampLight.position.copy(lp).add(new THREE.Vector3(0, 0.06, 0));
  }
  lampLight.castShadow = true;
  lampLight.shadow.mapSize.set(1024, 1024);
  lampLight.shadow.camera.near = 0.08;
  lampLight.shadow.camera.far = 14;
  lampLight.shadow.bias = -0.002;
  lampLight.shadow.normalBias = 0.03;
  lampLight.shadow.radius = 6;
  lampLight.visible = false;
  const moon = new THREE.DirectionalLight(0x8da2d8, 0);
  moon.position.copy(sun.position);
  moon.target.position.copy(c);
  moon.visible = false;
  scene.add(lampLight, moon, moon.target);
  const shadeMat = lampMesh ? ((lampMesh as THREE_NS.Mesh).material as THREE_NS.MeshPhysicalMaterial) : null;
  const glassMats: THREE_NS.MeshPhysicalMaterial[] = [];
  for (const w of windows) {
    byKey[w.key]?.traverse((o) => {
      const m = o as THREE_NS.Mesh;
      if (m.isMesh && m.name.startsWith("glass-")) glassMats.push(m.material as THREE_NS.MeshPhysicalMaterial);
    });
  }
  const glassDay = glassMats.map((m) => m.emissiveIntensity);
  const bgEl = renderer.domElement.parentElement;
  const bgWas = bgEl ? bgEl.style.background : "";
  const exposureWas = renderer.toneMappingExposure;
  const cool = new THREE.Color(0x6f86c8);
  let mode: RoomMode = bundle.mode === "night" ? "night" : "day";
  const applyMode = (m: RoomMode, notify = true) => {
    if (!diorama) return;
    mode = m;
    const day = m === "day";
    sun.visible = day;
    sun.intensity = params.day.sun;
    sun.shadow.radius = params.day.radius;
    moon.visible = !day;
    moon.intensity = params.night.moon;
    lampLight.visible = !day && lampMesh !== null;
    lampLight.intensity = params.night.lamp;
    for (const s of shellLights) {
      const t = s.l.type;
      const k = day
        ? t === "AmbientLight" ? params.day.ambient : t === "HemisphereLight" ? params.day.hemi : params.day.key
        : t === "AmbientLight" ? params.night.ambient : t === "HemisphereLight" ? params.night.hemi : params.night.key;
      s.l.intensity = s.was * k;
      s.l.color.copy(s.color);
      if (!day) s.l.color.lerp(cool, 0.55);
    }
    if (lampMesh) (lampMesh as THREE_NS.Mesh).castShadow = day; // the lamp's own bulb sits inside the shade
    if (shadeMat) {
      shadeMat.emissive.set(0xffcf8a);
      shadeMat.emissiveIntensity = day ? 0 : 0.65;
    }
    glassMats.forEach((g, i) => {
      g.emissiveIntensity = day ? glassDay[i] : 0.04;
    });
    if (bgEl) {
      bgEl.style.transition = "background 0.4s";
      bgEl.style.background = day ? bgWas : "radial-gradient(120% 90% at 50% 42%, #2b2a2c 0%, #1b1a1c 55%, #0e0e10 100%)";
    }
    renderer.toneMappingExposure = day ? exposureWas : params.night.exposure;
    toggleLabel();
    if (notify) opts.onChange?.(); // not at build time: the viewer's redraw clock does not exist yet
  };
  // The little control beside the view pill: ☀ day / ☾ night.
  let toggle: HTMLButtonElement | null = null;
  const toggleLabel = () => {
    if (toggle) toggle.textContent = mode === "day" ? "☀ day" : "☾ night";
  };
  if (diorama && opts.domParent) {
    toggle = document.createElement("button");
    Object.assign(toggle.style, {
      position: "absolute",
      right: "22px",
      bottom: "22px",
      padding: "8px 14px",
      border: "0",
      borderRadius: "999px",
      background: "rgba(255,255,255,0.62)",
      backdropFilter: "blur(10px)",
      boxShadow: "0 1px 10px rgba(80,70,55,0.12)",
      font: "14px system-ui",
      color: "#4a4339",
      cursor: "pointer",
      userSelect: "none",
      zIndex: "5",
    } as CSSStyleDeclaration);
    toggle.setAttribute("aria-label", "Switch between day and night");
    toggle.onclick = () => applyMode(mode === "day" ? "night" : "day");
    opts.domParent.appendChild(toggle);
  }
  applyMode(mode, false);

  return {
    root,
    byKey,
    mode: () => mode,
    setMode: (m) => applyMode(m),
    params,
    update: (camera) => {
      for (const w of walled) w.g.visible = w.nx * (camera.position.x - w.g.position.x) + w.nz * (camera.position.z - w.g.position.z) > 0;
    },
    dispose: () => {
      scene.remove(root, sun, sun.target, lampLight, moon, moon.target);
      toggle?.remove();
      if (bgEl) bgEl.style.background = bgWas;
      renderer.toneMappingExposure = exposureWas;
      for (const r of restore) r();
      for (const d of disposables) d.dispose();
    },
  };
}
