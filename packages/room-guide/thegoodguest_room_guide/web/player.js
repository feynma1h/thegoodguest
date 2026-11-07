// The guide's player: plays a motion plan in the diorama viewer, and shows what the
// guide points at.
//
// It runs inside the viewer's own page (the harness injects it as a module, so it
// shares the viewer's three.js) and touches the viewer only through
// window.__diorama: its scene, its walls, its light rig and its render call. It edits
// none of the viewer's files.
//
// A plan (motion.py's plan_json) gives every moving piece keyframes of time, position
// and turn. Between two keyframes a piece moves along the straight line with
// smoothstep easing, exactly as motion.py checked it, so what plays is what was
// checked: nothing passes through anything.
//
// It also measures every piece's real parts, as the viewer drew them, and hands them
// to the harness, so the engine collides with what you see.
//
// Read by: harness.html (injected into the viewer's frame).
import * as THREE from 'three';

const D = window.__diorama;
const groups = new Map();       // piece id -> its group
const homes = new Map();        // piece id -> the wall group it hangs in, if any
let sceneData = null;

function index() {
  const tops = [];
  const objects = D.scene.getObjectByName('objects');
  if (objects) for (const g of objects.children) tops.push([g, null]);
  for (const [id, w] of D.room.walls) for (const g of w.items.children) tops.push([g, id]);
  for (const [g, wall] of tops) {
    let owner = null;
    g.traverse((m) => { if (!owner && m.userData && m.userData.owner) owner = m.userData.owner; });
    if (owner) { groups.set(owner.id, g); if (wall) homes.set(owner.id, wall); }
  }
}

const smoothstep = (u) => { u = Math.min(1, Math.max(0, u)); return u * u * (3 - 2 * u); };

function poseAt(keys, t) {
  if (t <= keys[0].t) return keys[0];
  for (let i = 0; i < keys.length - 1; i++) {
    const a = keys[i], b = keys[i + 1];
    if (t <= b.t) {
      if (b.t - a.t <= 1e-9) return b;
      const s = smoothstep((t - a.t) / (b.t - a.t));
      return { x: a.x + (b.x - a.x) * s, y: a.y + (b.y - a.y) * s, z: a.z + (b.z - a.z) * s, yaw: a.yaw + (b.yaw - a.yaw) * s };
    }
  }
  return keys[keys.length - 1];
}

function worldPose(g) {
  const p = new THREE.Vector3(), q = new THREE.Quaternion();
  g.updateMatrixWorld(true);
  g.matrixWorld.decompose(p, q, new THREE.Vector3());
  return { x: p.x, y: p.y, z: p.z, yaw: new THREE.Euler().setFromQuaternion(q, 'YXZ').y };
}

function lightsOf(pid) {
  return D.rig.sources.filter((s) => s.def.object === pid);
}

// ---------------------------------------------------------------- overlays on the floor
const overlay = new THREE.Group();
overlay.name = 'guide-overlay';
D.scene.add(overlay);
const PAPER = 0xf6f0ea, ACCENT = 0xa8402f;

function rect(x, z, hx, hz, yaw, color, { dashed = false, fill = 0, y = 0.006 } = {}) {
  const g = new THREE.Group();
  const pts = [[hx, hz], [-hx, hz], [-hx, -hz], [hx, -hz], [hx, hz]].map(([a, b]) => new THREE.Vector3(a, 0, b));
  const geom = new THREE.BufferGeometry().setFromPoints(pts);
  const mat = dashed
    ? new THREE.LineDashedMaterial({ color, dashSize: 0.06, gapSize: 0.04, transparent: true, opacity: 0.95 })
    : new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.95 });
  const line = new THREE.Line(geom, mat);
  if (dashed) line.computeLineDistances();
  g.add(line);
  if (fill > 0) {
    const plane = new THREE.Mesh(new THREE.PlaneGeometry(2 * hx, 2 * hz),
      new THREE.MeshBasicMaterial({ color, transparent: true, opacity: fill, depthWrite: false, side: THREE.DoubleSide }));
    plane.rotation.x = -Math.PI / 2;
    g.add(plane);
  }
  g.position.set(x, y, z);
  g.rotation.y = yaw;
  overlay.add(g);
  return g;
}

function clearOverlay(kind) {
  for (const c of [...overlay.children]) if (!kind || c.userData.kind === kind) overlay.remove(c);
}

// ---------------------------------------------------------------- playing a plan
let playing = null;

function play(plan) {
  if (!groups.size) index();
  if (playing) playing.cancel = true;
  const state = { cancel: false };
  playing = state;
  const starts = new Map();
  for (const pid of Object.keys(plan.tracks)) {
    const g = groups.get(pid);
    if (!g) continue;
    if (homes.has(pid)) D.scene.attach(g);          // carried in world space while it moves
    starts.set(pid, { pose: worldPose(g), lights: lightsOf(pid).map((s) => s.light.position.clone()) });
  }
  return new Promise((resolve) => {
    const t0 = performance.now();
    function step(now) {
      if (state.cancel) { resolve(false); return; }
      const t = Math.min(plan.duration, (now - t0) / 1000);
      for (const [pid, keys] of Object.entries(plan.tracks)) {
        const g = groups.get(pid);
        if (!g) continue;
        const k = poseAt(keys, t);
        g.position.set(k.x, k.y, k.z);
        g.rotation.set(0, k.yaw, 0);
        const s0 = starts.get(pid);
        const dyaw = k.yaw - s0.pose.yaw, c = Math.cos(dyaw), sn = Math.sin(dyaw);
        lightsOf(pid).forEach((src, i) => {
          const L = s0.lights[i];
          const rx = L.x - s0.pose.x, rz = L.z - s0.pose.z;
          src.light.position.set(k.x + rx * c + rz * sn, L.y + (k.y - s0.pose.y), k.z - rx * sn + rz * c);
        });
      }
      D.render();
      if (t < plan.duration) requestAnimationFrame(step);
      else { settle(plan); playing = null; resolve(true); }
    }
    requestAnimationFrame(step);
  });
}

// Back into the wall it now hangs on, so it hides with that wall like any other.
function settle(plan) {
  for (const [pid, wallId] of Object.entries(plan.walls || {})) {
    const g = groups.get(pid), w = D.room.walls.get(wallId);
    if (g && w) { w.items.attach(g); homes.set(pid, wallId); }
  }
  D.render();
}

// Put pieces at poses at once (used when the room is opened on a kept arrangement).
function place(poses) {
  if (!groups.size) index();
  const tracks = {};
  for (const [pid, p] of Object.entries(poses)) tracks[pid] = [{ t: 0, ...p }];
  return play({ tracks, duration: 0, walls: {} });
}

// ---------------------------------------------------------------- what the guide points at
function show(focus) {
  clearOverlay('focus');
  for (const f of focus.footprints || []) {           // where a piece stood before it moved
    const r = rect(f.x, f.z, f.hx, f.hz, f.yaw, PAPER, { dashed: true });
    r.userData.kind = 'focus';
  }
  for (const z of focus.zones || []) {                 // a space something needs, or a pinch
    const r = rect(z.x, z.z, z.hx, z.hz, z.yaw, ACCENT, { fill: 0.18 });
    r.userData.kind = 'focus';
  }
  for (const pid of focus.pieces || []) {              // a piece the guide is talking about
    const g = groups.get(pid);
    if (!g) continue;
    const box = new THREE.Box3().setFromObject(g);
    const c = box.getCenter(new THREE.Vector3()), s = box.getSize(new THREE.Vector3());
    const r = rect(c.x, c.z, s.x / 2 + 0.04, s.z / 2 + 0.04, 0, ACCENT);
    r.userData.kind = 'focus';
  }
  if (typeof focus.view === 'number') D.goTo(focus.view);
  if (typeof focus.night === 'boolean') D.setMode(focus.night);
  D.render();
}

// ---------------------------------------------------------------- real parts, for the engine
// Each mesh's box, in its piece's own frame (origin at the middle of its footprint
// on the floor, +Z its front), as [cx, cy, cz, hx, hy, hz]. Parts smaller than 2 cm
// every way are left out.
function solids() {
  if (!groups.size) index();
  const out = {};
  const inv = new THREE.Matrix4(), m = new THREE.Matrix4(), b = new THREE.Box3();
  for (const [pid, g] of groups) {
    g.updateMatrixWorld(true);
    inv.copy(g.matrixWorld).invert();
    const parts = [];
    g.traverse((mesh) => {
      if (!(mesh.isMesh || mesh.isInstancedMesh) || !mesh.geometry) return;
      if (mesh.isInstancedMesh) mesh.computeBoundingBox(); else mesh.geometry.computeBoundingBox();
      const local = mesh.isInstancedMesh ? mesh.boundingBox : mesh.geometry.boundingBox;
      if (!local || local.isEmpty()) return;
      m.multiplyMatrices(inv, mesh.matrixWorld);
      b.copy(local).applyMatrix4(m);
      const c = b.getCenter(new THREE.Vector3()), s = b.getSize(new THREE.Vector3());
      if (Math.max(s.x, s.y, s.z) < 0.02) return;
      parts.push([c.x, c.y, c.z, s.x / 2, s.y / 2, s.z / 2].map((v) => +v.toFixed(4)));
    });
    if (parts.length) out[pid] = parts;
  }
  return out;
}

index();
window.__guidePlayer = { play, place, show, clear: () => { clearOverlay(); D.render(); }, solids, groups };
window.dispatchEvent(new Event('guide-player-ready'));
