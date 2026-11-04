/**
 * Local-only comparison harness (flag-guarded; see SplatViewer's
 * __shellFinishView hook). Poses the viewer's camera exactly where a real
 * camera frame was taken, renders the finish twice — the real look, and a
 * flat "region id" pass — and POSTs both PNGs to tools/serve_scene.py.
 * tools/finish_compare.py turns those into a photo | render sheet and a
 * per-region colour comparison against the photo.
 *
 * Region ids are the red channel of the id pass: see REGION_IDS. The id
 * pass swaps every shell mesh to an unlit material whose colour comes from
 * the mesh's userData.region (set by shellFinishScene), so nothing about the
 * drawing changes and no photo data enters the app.
 */

import type * as THREE_NS from "three";

type T = typeof THREE_NS;

/** Red-channel ids of the id pass (0 = nothing drawn). */
export const REGION_IDS = {
  paint: 40,
  tile: 80,
  floor: 120,
  door: 160,
  glass: 200,
  casing: 240,
} as const;

export interface HarnessFrame {
  id: number;
  pos: [number, number, number];
  quat: [number, number, number, number];
  fy: number;
  h: number;
  /** Sensor width/height in px: the render is sized to the same aspect (a
   * viewer pane of another shape would crop or stretch the field of view). */
  w?: number;
  /** Output scale vs the sensor (default 0.75 -> 1440x1080). */
  scale?: number;
}

export interface MeshRegion {
  /** A wall: paint above, tile below `bandFrac` of the wall's height. */
  wall?: { bandFrac: number };
  /** A whole mesh in one region. */
  whole?: keyof typeof REGION_IDS;
}

export function makeCompareHarness(
  THREE: T,
  camera: THREE_NS.PerspectiveCamera,
  controls: { update: () => void },
  renderer: THREE_NS.WebGLRenderer,
  scene: THREE_NS.Scene,
  beforeRender: (camera: THREE_NS.Camera) => void = () => {},
) {
  const idMaterial = (m: MeshRegion): THREE_NS.Material | null => {
    if (m.whole) {
      const r = REGION_IDS[m.whole] / 255;
      return new THREE.MeshBasicMaterial({ color: new THREE.Color().setRGB(r, 0, 0, THREE.LinearSRGBColorSpace), toneMapped: false });
    }
    if (m.wall) {
      // 1 x 256 strip in the wall's uv.v: paint above the band, tile below.
      const c = document.createElement("canvas");
      c.width = 1;
      c.height = 256;
      const ctx = c.getContext("2d")!;
      const cut = Math.round((1 - m.wall.bandFrac) * 256); // canvas y down
      ctx.fillStyle = `rgb(${REGION_IDS.paint},0,0)`;
      ctx.fillRect(0, 0, 1, cut);
      ctx.fillStyle = `rgb(${REGION_IDS.tile},0,0)`;
      ctx.fillRect(0, cut, 1, 256 - cut);
      const tex = new THREE.CanvasTexture(c);
      tex.colorSpace = THREE.NoColorSpace;
      tex.magFilter = tex.minFilter = THREE.NearestFilter;
      tex.generateMipmaps = false;
      return new THREE.MeshBasicMaterial({ map: tex, toneMapped: false });
    }
    return null;
  };

  const pose = (f: HarnessFrame) => {
    controls.update = () => {};
    if (f.w) {
      const k = f.scale ?? 0.75;
      renderer.setPixelRatio(1);
      renderer.setSize(Math.round(f.w * k), Math.round(f.h * k), false);
      camera.aspect = f.w / f.h;
    }
    camera.near = 0.02; // in-room frames need the fine near plane the diorama rig widens
    camera.far = 100;
    camera.fov = (2 * Math.atan(f.h / 2 / f.fy) * 180) / Math.PI;
    camera.position.set(...f.pos);
    camera.quaternion.set(...f.quat);
    camera.updateProjectionMatrix();
  };

  const post = async (port: number, name: string, dataUrl: string) => {
    await fetch(`http://127.0.0.1:${port}/renders/${name}.png`, { method: "POST", body: dataUrl });
  };

  /** Furniture mask pass: every twin flat in its own id (red = 30 x (index+1),
   * linear), shell and contact shadows hidden. Lets the python side measure
   * the photo's colours exactly where the render says the piece is. */
  const maskPass = async (f: HarnessFrame, port: number) => {
    const root = scene.getObjectByName("furniture-twins");
    if (!root) return;
    const saved: Array<[THREE_NS.Mesh, THREE_NS.Material | THREE_NS.Material[], boolean]> = [];
    scene.traverse((o) => {
      const mesh = o as THREE_NS.Mesh;
      if (mesh.isMesh) saved.push([mesh, mesh.material, mesh.visible]);
    });
    const tmp: THREE_NS.Material[] = [];
    for (const [mesh] of saved) mesh.visible = false;
    root.children.forEach((g, idx) => {
      const m = new THREE.MeshBasicMaterial({
        color: new THREE.Color().setRGB((30 * (idx + 1)) / 255, 0, 0, THREE.LinearSRGBColorSpace),
        toneMapped: false,
      });
      tmp.push(m);
      g.traverse((o) => {
        const mesh = o as THREE_NS.Mesh;
        if (mesh.isMesh && mesh.name !== "contact-shadow") {
          mesh.material = m;
          mesh.visible = true;
        }
      });
    });
    const bg = scene.background;
    scene.background = null;
    const prev = renderer.getClearAlpha();
    renderer.setClearColor(0x000000, 0);
    renderer.render(scene, camera);
    await post(port, `mask_${f.id}`, renderer.domElement.toDataURL("image/png"));
    renderer.setClearAlpha(prev);
    scene.background = bg;
    for (const [mesh, mat, vis] of saved) {
      mesh.material = mat;
      mesh.visible = vis;
    }
    for (const m of tmp) m.dispose();
  };

  const run = async (frames: HarnessFrame[], port: number) => {
    const done: number[] = [];
    for (const f of frames) {
      pose(f);
      beforeRender(camera);
      renderer.render(scene, camera);
      await post(port, `frame_${f.id}`, renderer.domElement.toDataURL("image/png"));

      // Id pass.
      const saved: Array<[THREE_NS.Mesh, THREE_NS.Material | THREE_NS.Material[]]> = [];
      const bg = scene.background;
      scene.background = null;
      scene.traverse((o) => {
        const mesh = o as THREE_NS.Mesh;
        const region = mesh.userData?.region as MeshRegion | undefined;
        if (!mesh.isMesh) return;
        if (!region) {
          if (mesh.visible) {
            saved.push([mesh, mesh.material]);
            mesh.visible = false;
            (mesh as unknown as { __hid?: boolean }).__hid = true;
          }
          return;
        }
        const m = idMaterial(region);
        if (m) {
          saved.push([mesh, mesh.material]);
          mesh.material = m;
        }
      });
      const prev = renderer.getClearAlpha();
      renderer.setClearColor(0x000000, 0);
      renderer.render(scene, camera);
      await post(port, `ids_${f.id}`, renderer.domElement.toDataURL("image/png"));
      renderer.setClearAlpha(prev);
      for (const [mesh, mat] of saved) {
        const hid = (mesh as unknown as { __hid?: boolean }).__hid;
        if (hid) {
          mesh.visible = true;
          delete (mesh as unknown as { __hid?: boolean }).__hid;
        } else {
          (mesh.material as THREE_NS.Material).dispose();
          mesh.material = mat;
        }
      }
      scene.background = bg;
      await maskPass(f, port);
      done.push(f.id);
    }
    return done;
  };

  /** Run the frames listed in a poses.json the scene server hands out
   * (tools/furniture_compare.py poses writes it), so a loop step is one short call. */
  const runFrom = async (port: number) => {
    const frames = (await (await fetch(`http://127.0.0.1:${port}/poses.json`, { cache: "no-store" })).json()) as HarnessFrame[];
    return run(frames, port);
  };

  return { run, runFrom, pose };
}
