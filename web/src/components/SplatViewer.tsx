"use client";

/**
 * SplatViewer — the ONLY module in this app that touches the rendering
 * library. Everything else speaks PositionedSplat (lib/api/types.ts):
 * "a splat file URL plus a world transform". Swapping Spark for another
 * renderer is a rewrite of this file and nothing else — keep it that way.
 *
 * Renderer: three.js + @sparkjsdev/spark (WebGL2 3DGS renderer; decision
 * 0053). Both are imported dynamically inside useEffect so the static
 * export never evaluates GPU/browser globals at build time.
 *
 * Coordinate frames: PositionedSplat transforms are ARKit-world (right-
 * handed, +Y up, meters) — the same handedness and up-axis as three.js,
 * so transforms apply directly with no basis change.
 *
 * Staging: the room is presented, not just rendered — a warm dark stage
 * (the Good Guest palette's ambient register), a radially-fading 1m grid
 * disc, bounded orbit, and a short dolly-in on arrival. Spark's splat
 * shaders ignore three.js fog, so all depth falloff here is texture/CSS.
 *
 * Reveal (design §4, redesigned by decision 0097): with `reveal`, the room
 * draws its measured boundary first — a pen tracing the floor perimeter,
 * verticals rising at the corners, the top edge closing the box — then the
 * surfaces MATERIALIZE IN PLACE inside it (fade only; nothing translates),
 * then the pieces settle, easing down a few centimetres on a curve that
 * starts and ends at rest. `onRevealStep` fires for the pieces the guest
 * introduces by name, `onRevealCaptionsDone` when the last name should
 * leave, and `onRevealDone` after a beat of quiet. Without a shell the
 * pieces settle on the honest grid. Reduced motion collapses to an
 * immediate full room with no captions.
 *
 * This file PLAYS the choreography; lib/reveal DECIDES it — every cue's
 * timing, ordering and naming is a pure function there, pinned by tests,
 * because the pacing cannot be judged in a throttled automation browser.
 *
 * Shell rendering (decisions 0069/0077): single-sided PARAMETRIC
 * surfaces — MeshStandardMaterial built from each plane's measured albedo
 * + family roughness (no textures exist in the shell contract; the bake
 * left serving). Walls arrive as interior-wound polygons: v2 quads take
 * the fast path, v3 polygon walls (roomplan verbatim geometry, the
 * anchor-envelope degrade) triangulate in their own plane via the
 * lib/shell3d frame — which also places door/window/opening inset
 * patches, since v3 corner 0 need not be the UV origin. The floor is a
 * triangulated polygon (rendered shape verbatim). A small warm light rig
 * shades the standard materials — Spark's splat shaders ignore three.js
 * lights, so objects are unaffected. Planes without a measured albedo
 * render the flat warm neutral (honestly unobserved; nothing fake).
 * depthWrite:true meshes composite correctly with Spark splats (the 0066
 * V1 depth probe).
 */

import { useEffect, useMemo, useRef, useState } from "react";

import type { PositionedSplat, ShellPlane } from "@/lib/api/types";
import { viewerYawRad } from "@/lib/clipSign";
import {
  SETTLE_DROP_M,
  SETTLE_FADE_FRACTION,
  pathLengths,
  pathPointAt,
  planReveal,
  revealHoldMs,
  settleEase,
  windowProgress,
} from "@/lib/reveal";
import { openingRect, projectToWallPlane, wallFrame } from "@/lib/shell3d";
import { labelsKey, outlinesKey, rendererKey } from "@/lib/viewerKey";

interface SplatViewerProps {
  splats: PositionedSplat[];
  /** Room shell (decisions 0066/0069): parametric world-space surfaces
   * rendered as the stage under the objects. Single-sided, so the
   * orbiting camera sees through the near wall (the dollhouse cutaway —
   * proven with the V1 depth probe: Spark splats depth-composite
   * correctly against depthWrite:true meshes both ways). Absent/null
   * keeps the grid. */
  shell?: ShellPlane[] | null;
  className?: string;
  /** Slow auto-orbit until the user grabs the scene (landing demo). */
  idleOrbit?: boolean;
  /** Full-bleed stage: no rounded frame, no hairline (immersive room). */
  frameless?: boolean;
  /** Play the reveal on load (decision 0097). */
  reveal?: boolean;
  /** Fires for each piece the guest introduces by name — the leading few,
   * not every arrival (the tail flows in unnamed). */
  onRevealStep?: (index: number, label: string) => void;
  /** The last name has had its dwell; the DOM should clear the caption
   * while the remaining pieces flow in. */
  onRevealCaptionsDone?: () => void;
  onRevealDone?: () => void;
  /** Dev-workbench badges: short texts floated at world positions — wall
   * letters and piece numbers, so a reviewer can name what they are looking
   * at. Renderer-agnostic input like everything else here; null/absent
   * renders nothing. */
  labels?: ViewerLabel[] | null;
  /** Measured footprints of pieces a proposal has moved or removed
   * (decision 0131): the measurement survives on screen as its outline,
   * drawn on the floor in the reveal's contour language — the pen in the
   * paper tone, which in this room MEANS measurement. Renderer-agnostic
   * world geometry; null/absent draws nothing. */
  outlines?: MeasuredOutline[] | null;
}

/** One measured footprint: a yaw-oriented rectangle on the floor. Same
 * shape as a clip volume's footprint because it comes from the same
 * measured RoomPlan box. */
export interface MeasuredOutline {
  center_world: [number, number, number];
  half_extents_m: [number, number, number];
  yaw_rad: number;
}

/** The slice of a Spark SplatMesh the placement seam touches. Structural,
 * so the transform effect needs no Spark types at module scope (decision
 * 0053's containment rule cuts both ways). */
interface SplatMeshHandle {
  position: { set(x: number, y: number, z: number): void; y: number };
  quaternion: { set(x: number, y: number, z: number, w: number): void };
  scale: { set(x: number, y: number, z: number): void; setScalar(v: number): void };
  visible: boolean;
  opacity: number;
}

/** Write one splat's world placement onto its live mesh. The clip volume
 * is parented to the mesh in its LOCAL frame, so it follows this without
 * being recomputed — a moved piece carries its measured box with it, which
 * is exactly right: the box is the object's, not the room's. */
function applyPlacement(mesh: SplatMeshHandle, s: PositionedSplat): void {
  mesh.position.set(...s.position);
  mesh.quaternion.set(...s.rotation_xyzw);
  if (typeof s.scale === "number") mesh.scale.setScalar(s.scale);
  else mesh.scale.set(...s.scale);
}

/** Push the current placement of every splat onto the live meshes.
 * `hidden` is honoured here rather than by dropping the splat from the
 * array: unmounting a mesh is a full re-download (decision 0130 measured
 * it), and a removal the person can undo must cost nothing to undo. */
function applyLivePlacements(
  meshes: SplatMeshHandle[],
  splats: PositionedSplat[],
  revealOwnsVisibility: boolean,
): void {
  for (let i = 0; i < meshes.length; i++) {
    const s = splats[i];
    if (!s) continue;
    applyPlacement(meshes[i], s);
    if (!revealOwnsVisibility) meshes[i].visible = !s.hidden;
  }
}

/** One floating badge: 1–2 chars at a world position. kind picks color
 * (box = orange, tail = blue, wall = brown). */
export interface ViewerLabel {
  text: string;
  position: [number, number, number];
  kind?: "box" | "tail" | "wall";
}

/* --- Decorations: things drawn into the room that come and go WHILE the
 * renderer is alive. They are built by their own effects (decision 0188),
 * not by the build effect, because the build effect's key is global: an
 * outline appearing used to change it and take every splat mesh down with
 * it, re-downloading the whole room to add five vertices to the floor.
 *
 * Each builder is a pure function of (three, scene, input) returning what
 * it added, so its effect can put it back exactly. */

/** The three.js module namespace, as a type only — the runtime import stays
 * inside the build effect, so decision 0053's containment rule is intact. */
type ThreeModule = typeof import("three");

/** What a decoration effect needs to draw. Published by the build effect
 * once the renderer exists; cleared when it is torn down. */
interface SceneSeam {
  three: ThreeModule;
  scene: InstanceType<ThreeModule["Scene"]>;
}

/** One thing added to the scene, with the means to take it back out. */
interface Decoration {
  object: InstanceType<ThreeModule["Object3D"]>;
  dispose: () => void;
}

/** Where a moved piece was measured (decision 0131). Its footprint stays
 * on the floor in the contour's own line and tone, because in this room
 * that line means MEASUREMENT — the same language the reveal used to draw
 * the boundary. Not a badge, not a ghost of the object: the measurement,
 * still there, one field away from the proposal both on screen and in the
 * document. */
function buildOutlines(
  { three, scene }: SceneSeam,
  outlines: MeasuredOutline[],
): Decoration[] {
  const built: Decoration[] = [];
  for (const o of outlines) {
    const [hx, , hz] = o.half_extents_m;
    // Same inline map as three.js R_y(+θ), through the same lib/clipSign
    // convention as the clip volume — so the outline agrees with the clip
    // AND with the solver that produced the footprint (0135/0112). One
    // convention, never two half-flipped surfaces.
    const yawEff = viewerYawRad(o.yaw_rad);
    const cos = Math.cos(yawEff);
    const sin = Math.sin(yawEff);
    // The box's own base, lifted a hair so it sits ON the floor rather than
    // z-fighting it. Derived from the measurement itself, not from the
    // shell — an outline must survive a room with no floor.
    const y = o.center_world[1] - o.half_extents_m[1] + 0.004;
    const corners: [number, number, number][] = (
      [
        [-hx, -hz],
        [hx, -hz],
        [hx, hz],
        [-hx, hz],
        [-hx, -hz],
      ] as [number, number][]
    ).map(([u, v]) => [
      o.center_world[0] + u * cos + v * sin,
      y,
      o.center_world[2] - u * sin + v * cos,
    ]);
    const geometry = new three.BufferGeometry().setAttribute(
      "position",
      new three.Float32BufferAttribute(corners.flat(), 3),
    );
    const material = new three.LineBasicMaterial({
      color: CONTOUR_COLOR,
      transparent: true,
      opacity: CONTOUR_FLOOR_OPACITY,
      depthWrite: false,
    });
    const line = new three.Line(geometry, material);
    scene.add(line);
    built.push({
      object: line,
      dispose: () => {
        geometry.dispose();
        material.dispose();
      },
    });
  }
  return built;
}

/** Dev walk badges: always-on-top sprites, one per label. Canvas circle +
 * text, no external assets (CSP holds). */
function buildLabels(
  { three, scene }: SceneSeam,
  labels: ViewerLabel[],
): Decoration[] {
  const built: Decoration[] = [];
  for (const l of labels) {
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = 128;
    const ctx = canvas.getContext("2d");
    if (!ctx) continue;
    const bg =
      l.kind === "wall" ? "#6b5d49" : l.kind === "tail" ? "#3d6b8e" : "#c66a4a";
    ctx.beginPath();
    ctx.arc(64, 64, 55, 0, Math.PI * 2);
    ctx.fillStyle = bg;
    ctx.fill();
    ctx.lineWidth = 7;
    ctx.strokeStyle = "#faf6ee";
    ctx.stroke();
    ctx.fillStyle = "#ffffff";
    ctx.font = "700 58px ui-monospace, Menlo, monospace";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(l.text, 64, 68);
    const tex = new three.CanvasTexture(canvas);
    const mat = new three.SpriteMaterial({
      map: tex,
      depthTest: false,
      transparent: true,
    });
    const sprite = new three.Sprite(mat);
    sprite.position.set(...l.position);
    sprite.scale.setScalar(l.kind === "wall" ? 0.42 : 0.3);
    sprite.renderOrder = 999;
    scene.add(sprite);
    built.push({
      object: sprite,
      dispose: () => {
        tex.dispose();
        mat.dispose();
      },
    });
  }
  return built;
}

/** Async-only load outcome, stamped with the splat-set key it belongs to.
 * "Loading" is derived (no outcome for the current key yet) so effects
 * never call setState synchronously (react-hooks/set-state-in-effect). */
type LoadOutcome = { key: string; phase: "ready" } | { key: string; phase: "error"; error: string };

/** Ground: a fine 1m grid that fades out radially, drawn to a canvas
 * texture — a measured stage under the room, in warm lamplight tones. */
function makeGroundTexture(): HTMLCanvasElement {
  const size = 1024;
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d")!;
  const center = size / 2;

  // Faint radial fill — the "contact pool" of light under the content.
  const pool = ctx.createRadialGradient(center, center, 0, center, center, center);
  pool.addColorStop(0, "rgba(247, 239, 223, 0.06)");
  pool.addColorStop(0.45, "rgba(247, 239, 223, 0.025)");
  pool.addColorStop(1, "rgba(247, 239, 223, 0)");
  ctx.fillStyle = pool;
  ctx.fillRect(0, 0, size, size);

  // Grid lines, alpha-masked by the same radial falloff. The plane is
  // GROUND_SIZE meters wide, so lines every size/GROUND_SIZE px = 1m.
  const step = size / GROUND_SIZE;
  ctx.strokeStyle = "rgba(247, 239, 223, 0.17)";
  ctx.lineWidth = 1;
  ctx.beginPath();
  for (let i = 0; i <= GROUND_SIZE; i++) {
    ctx.moveTo(i * step, 0);
    ctx.lineTo(i * step, size);
    ctx.moveTo(0, i * step);
    ctx.lineTo(size, i * step);
  }
  ctx.stroke();

  // Multiply the whole canvas by a radial alpha mask.
  ctx.globalCompositeOperation = "destination-in";
  const mask = ctx.createRadialGradient(center, center, 0, center, center, center * 0.95);
  mask.addColorStop(0, "rgba(0,0,0,0.9)");
  mask.addColorStop(0.55, "rgba(0,0,0,0.45)");
  mask.addColorStop(1, "rgba(0,0,0,0)");
  ctx.fillStyle = mask;
  ctx.fillRect(0, 0, size, size);
  ctx.globalCompositeOperation = "source-over";

  return canvas;
}

const GROUND_SIZE = 16; // meters; also the grid line count (1m spacing)

/* Reveal look (decision 0097; all timing lives in lib/reveal). The contour
 * is the MEASUREMENT — drawn in the paper tone, not gold, which the design
 * system reserves for light semantics. The floor's own perimeter reads
 * brightest because it is the room's real footprint; the verticals and the
 * top edge are its extent, and stay quieter. */
const CONTOUR_COLOR = 0xf7efdf;
const CONTOUR_FLOOR_OPACITY = 0.62;
const CONTOUR_EDGE_OPACITY = 0.32;
const CONTOUR_DOT_COLOR = 0xfff6e6;
/** The pen: a few dots riding at and just behind the drawing tip. */
const CONTOUR_DOT_COUNT = 3;
/** Dot spacing behind the tip, as a fraction of the perimeter. */
const CONTOUR_DOT_SPACING = 0.035;
const CONTOUR_DOT_SIZE_PX = 5;

/** Unobserved planes (albedo null) get a flat warm neutral — a surface
 * honestly present but never measured; nothing fake renders. */
const SHELL_NEUTRAL = 0x4a4136;
/** Opening insets darken their wall's surface color — a recessed panel
 * reading, not a guessed door/window appearance. */
const OPENING_DARKEN = 0.78;
/** Inset patches float this far off the wall toward the room (meters) so
 * they never z-fight the wall quad. */
const OPENING_OFFSET_M = 0.006;

export default function SplatViewer({
  splats,
  shell = null,
  className,
  idleOrbit = false,
  frameless = false,
  reveal = false,
  onRevealStep,
  onRevealCaptionsDone,
  onRevealDone,
  labels = null,
  outlines = null,
}: SplatViewerProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  // The renderer key carries only what needs a NEW RENDERER — which files
  // are in the scene, and the fixed geometry surrounding them. Everything
  // that changes while the renderer is alive lives elsewhere, because this
  // key is global: whatever is in it takes the whole room down with it, and
  // rebuilding a splat means re-downloading it (47.2 MB / 14–19 s on the
  // reference room; 0123/0125, re-confirmed in 0188). Transforms left in
  // decision 0133; measured outlines and walk badges left in 0188, into the
  // decoration effects below. `clip` stays because it is a different
  // GEOMETRY of the same file (a new SDF edit), not a placement of it —
  // and because a clip volume is parented to its mesh, so it follows a
  // move for free rather than needing to be rebuilt by one.
  const key = useMemo(() => rendererKey({ splats, shell }), [splats, shell]);
  // Decoration signatures: a caller handing us an equal-but-fresh array
  // must not rebuild anything, for the same reason the renderer key is a
  // string rather than an identity.
  const outlineSig = useMemo(() => outlinesKey(outlines), [outlines]);
  const labelSig = useMemo(() => labelsKey(labels), [labels]);
  const [outcome, setOutcome] = useState<LoadOutcome | null>(null);

  // Callback identity must not restart the renderer; refs are written
  // after commit (never during render) and read at call time.
  const revealStepRef = useRef(onRevealStep);
  const revealCaptionsDoneRef = useRef(onRevealCaptionsDone);
  const revealDoneRef = useRef(onRevealDone);
  useEffect(() => {
    revealStepRef.current = onRevealStep;
    revealCaptionsDoneRef.current = onRevealCaptionsDone;
    revealDoneRef.current = onRevealDone;
  });

  // `reveal` is read ONCE, when the renderer is built, and is deliberately
  // not an effect dependency. The caller turns it off when the reveal ends
  // (RoomStage moves to its settled phase); restarting the renderer there
  // would tear down and reload the room the user just watched assemble —
  // a blink at exactly the moment the reveal is supposed to have landed.
  const revealRef = useRef(reveal);

  // --- The transform seam (decision 0133). The renderer effect below owns
  // structure; these three refs own placement, so a proposal moves furniture
  // without the scene reloading. `splats` is read through the ref inside the
  // render loop for the same reason it is absent from the effect's
  // dependencies: an array identity change must never restart the renderer.
  const splatsRef = useRef(splats);
  const meshesRef = useRef<SplatMeshHandle[]>([]);
  // --- The decoration seam (decision 0188). The build effect publishes the
  // live scene here and bumps the epoch; the decoration effects below draw
  // into it. The epoch exists because the build is ASYNC: a decoration
  // effect that runs while the renderer is still importing three.js finds
  // no scene, does nothing, and must be re-run once there is one.
  const sceneRef = useRef<SceneSeam | null>(null);
  const [sceneEpoch, setSceneEpoch] = useState(0);
  // While the object wave is playing, visibility belongs to the reveal —
  // it is mid-sentence about which pieces have arrived, and a proposal
  // must not interrupt it. Ownership returns when the wave ends.
  const revealOwnsVisibilityRef = useRef(false);
  useEffect(() => {
    splatsRef.current = splats;
  });

  const hasContent = splats.length > 0 || (shell?.length ?? 0) > 0;
  const phase: "empty" | "loading" | "ready" | "error" = !hasContent
    ? "empty"
    : outcome?.key === key
      ? outcome.phase
      : "loading";
  const error = outcome?.key === key && outcome.phase === "error" ? outcome.error : null;

  useEffect(() => {
    if (splats.length === 0 && (shell?.length ?? 0) === 0) return;
    const container = containerRef.current;
    if (!container) return;

    let disposed = false;
    let cleanup: (() => void) | null = null;

    (async () => {
      try {
        const [
          THREE,
          { OrbitControls },
          {
            SparkRenderer,
            SplatMesh,
            SplatEdit,
            SplatEditSdf,
            SplatEditSdfType,
            SplatEditRgbaBlendMode,
          },
        ] =
          await Promise.all([
            import("three"),
            import("three/addons/controls/OrbitControls.js"),
            import("@sparkjsdev/spark"),
          ]);
        if (disposed) return;

        // alpha:true — the backdrop is the container's CSS gradient, which
        // gives the scene atmosphere no flat clear-color can.
        const renderer = new THREE.WebGLRenderer({ antialias: false, alpha: true });
        renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
        renderer.setSize(container.clientWidth, container.clientHeight);
        renderer.domElement.style.opacity = "0";
        renderer.domElement.style.transition = "opacity 900ms ease";
        renderer.domElement.style.cursor = "grab";
        container.appendChild(renderer.domElement);

        const scene = new THREE.Scene();

        const camera = new THREE.PerspectiveCamera(
          50,
          container.clientWidth / container.clientHeight,
          0.02,
          100,
        );

        const spark = new SparkRenderer({ renderer });
        scene.add(spark);

        const shellPlanes = shell ?? [];
        const shellHasFloor = shellPlanes.some((p) => p.kind === "floor");

        // The grid is the honest no-shell stage; when the shell brings the
        // room's real measured floor, the grid stands down.
        const ground = new THREE.Mesh(
          new THREE.PlaneGeometry(GROUND_SIZE, GROUND_SIZE),
          new THREE.MeshBasicMaterial({
            map: new THREE.CanvasTexture(makeGroundTexture()),
            transparent: true,
            depthWrite: false,
          }),
        );
        ground.rotation.x = -Math.PI / 2;
        if (!shellHasFloor) scene.add(ground);

        // --- Light rig for the parametric surfaces (0069): warm ambient +
        // a soft warm key from high in the room. Spark's splat shaders
        // ignore three.js lights, so objects render exactly as before;
        // only the shell's MeshStandardMaterials read these.
        scene.add(new THREE.AmbientLight(0xfff2df, 0.85));
        const keyLight = new THREE.DirectionalLight(0xffe7c4, 0.9);
        keyLight.position.set(3, 6, 2);
        scene.add(keyLight);

        // --- Room shell (0069): one single-sided parametric surface per
        // plane. Walls are quads; the floor triangulates its rendered
        // polygon. Material = measured albedo + family-looked-up
        // roughness; albedo null renders the honest neutral.
        // depthWrite:true — the configuration the 0066 V1 probe proved
        // composites with Spark splats.
        const makeShellMaterial = (p: ShellPlane, darken = 1) => {
          const color = new THREE.Color(
            p.material.albedo_hex ? p.material.albedo_hex : SHELL_NEUTRAL,
          ).multiplyScalar(darken);
          return new THREE.MeshStandardMaterial({
            color,
            roughness: p.material.roughness,
            metalness: 0,
            side: THREE.FrontSide,
            depthWrite: true,
          });
        };

        const shellMeshes = shellPlanes.map((p) => {
          const geom = new THREE.BufferGeometry();
          // Walls derive a UV frame from their polygon (lib/shell3d) —
          // shared by the N-corner triangulation and the opening patches.
          const frame = p.kind === "wall" ? wallFrame(p.corners) : null;
          if (p.kind === "wall" && p.corners.length === 4) {
            geom.setAttribute(
              "position",
              new THREE.Float32BufferAttribute(p.corners.flat(), 3),
            );
            geom.setIndex([0, 1, 2, 0, 2, 3]);
          } else if (p.kind === "wall") {
            // v3 polygon wall (decision 0077): triangulate in the wall's
            // own plane (earcut handles concave outlines), front face
            // along the winding's interior normal.
            geom.setAttribute(
              "position",
              new THREE.Float32BufferAttribute(p.corners.flat(), 3),
            );
            if (frame) {
              const uv = projectToWallPlane(p.corners, frame).map(
                ([u, v]) => new THREE.Vector2(u, v),
              );
              const tris = THREE.ShapeUtils.triangulateShape(uv, []);
              const indices = tris.flat();
              if (indices.length >= 3) {
                const [a, b, c] = indices;
                const va = new THREE.Vector3(...p.corners[a]);
                const vb = new THREE.Vector3(...p.corners[b]);
                const vc = new THREE.Vector3(...p.corners[c]);
                const n = vb.sub(va).cross(vc.sub(va));
                const front = new THREE.Vector3(...frame.normal);
                geom.setIndex(
                  n.dot(front) >= 0
                    ? indices
                    : tris.map((t) => [t[2], t[1], t[0]]).flat(),
                );
              }
            } else {
              // Degenerate frame (never emitted by the server): fan the
              // polygon rather than render nothing or crash.
              const fan: number[] = [];
              for (let i = 1; i + 1 < p.corners.length; i++) fan.push(0, i, i + 1);
              geom.setIndex(fan);
            }
          } else {
            // Floor polygon: triangulate in the XZ plane (handles concave
            // shapes), then orient front-face-up regardless of the source
            // winding — checked against the first triangle's normal.
            const pts2d = p.corners.map(
              (c) => new THREE.Vector2(c[0], c[2]),
            );
            const tris = THREE.ShapeUtils.triangulateShape(pts2d, []);
            const indices = tris.flat();
            geom.setAttribute(
              "position",
              new THREE.Float32BufferAttribute(p.corners.flat(), 3),
            );
            if (indices.length >= 3) {
              const [a, b, c] = indices;
              const va = new THREE.Vector3(...p.corners[a]);
              const vb = new THREE.Vector3(...p.corners[b]);
              const vc = new THREE.Vector3(...p.corners[c]);
              const n = vb.sub(va).cross(vc.sub(va));
              geom.setIndex(
                n.y >= 0
                  ? indices
                  : tris.map((t) => [t[2], t[1], t[0]]).flat(),
              );
            }
          }
          geom.computeVertexNormals();
          const mesh = new THREE.Mesh(geom, makeShellMaterial(p));
          scene.add(mesh);

          // Door/window/opening insets (0069, carried to v3): patches
          // slightly off the wall toward the room — a recessed panel in
          // the wall's own darkened color, never a guessed appearance.
          // Placement uses the wall's UV frame (bounding rect in-plane),
          // which reproduces the v2 corner-0 math exactly and stays
          // correct when v3 winding rotates the start corner.
          const extras: InstanceType<typeof THREE.Mesh>[] = [];
          if (p.kind === "wall" && frame) {
            for (const op of p.openings) {
              const rect = openingRect(frame, op.rect_uv, OPENING_OFFSET_M);
              const og = new THREE.BufferGeometry();
              og.setAttribute(
                "position",
                new THREE.Float32BufferAttribute(rect.flat(), 3),
              );
              og.setIndex([0, 1, 2, 0, 2, 3]);
              og.computeVertexNormals();
              const patch = new THREE.Mesh(
                og,
                makeShellMaterial(p, OPENING_DARKEN),
              );
              scene.add(patch);
              extras.push(patch);
            }
          }
          return { mesh, plane: p, extras };
        });

        // Uniform scale is the shipped contract; a per-axis triple is the
        // staged-fixture A/B side (see PositionedSplat.scale). Size-ordering
        // and camera-framing consumers reduce a triple to its largest axis.
        const scaleMax = (v: number | [number, number, number]) =>
          typeof v === "number" ? v : Math.max(...v);
        const meshes = splats.map((s, i) => {
          const mesh = new SplatMesh({ url: s.url });
          // Build from the LIVE placement, not this closure's: the effect
          // is async (three dynamic imports), so a proposal that landed
          // mid-load would otherwise be applied a frame later as a jump.
          applyPlacement(mesh, splatsRef.current[i] ?? s);
          scene.add(mesh);
          // Clip volume (decision 0104): a box-anchored splat may reach
          // past the measured box it is dressed in, and that mass is
          // known-false — the server declares it rather than moving or
          // rescaling the object to hide it. An inverted box SDF at zero
          // opacity deletes everything outside; Spark scopes an edit to
          // one mesh by parenting, so the SDF's LOCAL transform has to be
          // the box expressed in the mesh's frame.
          //
          // The yaw goes through lib/clipSign because `setFromAxisAngle(
          // [0,1,0], yaw)` is the OPPOSITE rotation to the server's
          // `yaw_rad` convention (decision 0135) — handing three.js the
          // raw yaw left the box 2θ from the one it is meant to cut,
          // amputating table legs and slicing mattress corners. The 0112
          // operator walk ruled for the measured sign (2026-08-12).
          if (s.clip) {
            mesh.updateMatrixWorld(true);
            const boxWorld = new THREE.Matrix4().compose(
              new THREE.Vector3(...s.clip.center_world),
              new THREE.Quaternion().setFromAxisAngle(
                new THREE.Vector3(0, 1, 0),
                viewerYawRad(s.clip.yaw_rad),
              ),
              new THREE.Vector3(...s.clip.half_extents_m),
            );
            const local = new THREE.Matrix4()
              .copy(mesh.matrixWorld)
              .invert()
              .multiply(boxWorld);
            const sdf = new SplatEditSdf({
              type: SplatEditSdfType.BOX,
              invert: true, // the region is everything OUTSIDE the box
              opacity: 0, // multiplied into alpha: outside disappears
            });
            local.decompose(sdf.position, sdf.quaternion, sdf.scale);
            const edit = new SplatEdit({
              rgbaBlendMode: SplatEditRgbaBlendMode.MULTIPLY,
              sdfs: [sdf],
            });
            edit.add(sdf);
            mesh.add(edit);
          }
          return mesh;
        });
        // Publish the placement seam. Any proposal that lands from here on
        // reaches these meshes through the transform effect, never through
        // a rebuild.
        meshesRef.current = meshes as unknown as SplatMeshHandle[];

        // Publish the decoration seam and wake the effects that own the
        // measured outlines and the walk badges (decision 0188). They draw
        // into this scene; nothing they do can reach the meshes above.
        sceneRef.current = { three: THREE, scene };
        setSceneEpoch((n) => n + 1);

        // --- Framing: fit the camera to the content, not the content to a
        // hardcoded camera. Object extents aren't known until meshes load,
        // so the radius is estimated from placements (position spread +
        // per-object scale as a proxy for size). Shell corners join the
        // fit so the whole room frames; with no objects (a shell-only
        // room) they carry the centroid too.
        const shellCorners = shellPlanes.flatMap((p) =>
          p.corners.map((c) => new THREE.Vector3(...c)),
        );
        const centroidSource =
          splats.length > 0
            ? splats.map((s) => new THREE.Vector3(...s.position))
            : shellCorners;
        const centroid = centroidSource
          .reduce((acc, v) => acc.add(v), new THREE.Vector3())
          .divideScalar(centroidSource.length);
        const radius = Math.max(
          1.4,
          ...splats.map(
            (s) =>
              centroid.distanceTo(new THREE.Vector3(...s.position)) +
              scaleMax(s.scale) * 1.2,
          ),
          ...shellCorners.map((c) => centroid.distanceTo(c)),
        );
        const target = new THREE.Vector3(
          centroid.x,
          Math.max(0.35, centroid.y * 0.75),
          centroid.z,
        );
        ground.position.set(centroid.x, 0, centroid.z);

        const fitDistance =
          (radius / Math.tan((camera.fov * Math.PI) / 360)) * 1.15;
        const finalOffset = new THREE.Vector3(
          Math.sin(Math.PI * 0.22) * fitDistance,
          fitDistance * 0.42,
          Math.cos(Math.PI * 0.22) * fitDistance,
        );

        const controls = new OrbitControls(camera, renderer.domElement);
        controls.enableDamping = true;
        controls.dampingFactor = 0.08;
        controls.target.copy(target);
        // Never under the floor, never inside an object, never lost in space.
        controls.maxPolarAngle = Math.PI / 2 - 0.05;
        controls.minDistance = radius * 0.5;
        controls.maxDistance = fitDistance * 3;

        controls.autoRotate = idleOrbit;
        controls.autoRotateSpeed = 0.5;
        let idleTimer: number | undefined;
        const onGrab = () => {
          renderer.domElement.style.cursor = "grabbing";
          if (!idleOrbit) return;
          controls.autoRotate = false;
          if (idleTimer !== undefined) clearTimeout(idleTimer);
          idleTimer = window.setTimeout(() => {
            controls.autoRotate = true;
          }, 8000);
        };
        const onRelease = () => {
          renderer.domElement.style.cursor = "grab";
        };
        renderer.domElement.addEventListener("pointerdown", onGrab);
        renderer.domElement.addEventListener("pointerup", onRelease);

        // --- The reveal (decision 0097). lib/reveal decides every cue;
        // this block builds what the cues drive and the render loop plays
        // them. Reduced motion produces an `immediate` plan — the room is
        // simply there, and nothing pretends to have materialized.
        const reducedMotion = window.matchMedia(
          "(prefers-reduced-motion: reduce)",
        ).matches;
        const plan = planReveal({ shell: shellPlanes, splats, reducedMotion });
        const assembling = revealRef.current && !plan.immediate;
        revealOwnsVisibilityRef.current = assembling;
        applyLivePlacements(meshesRef.current, splatsRef.current, assembling);

        // Which pieces have actually arrived (decision 0127). The reveal's
        // first two movements — the contour and the surfaces — need zero
        // splat bytes, so the stage is honest well before the room is
        // downloaded; the object wave then waits per piece rather than the
        // whole room waiting for its last byte.
        const arrived = new Set<number>();
        let objectHoldMs = 0;
        meshes.forEach((m, i) => {
          m.initialized.then(
            () => arrived.add(i),
            (err: unknown) => {
              // Count a failed piece as arrived: one broken splat must not
              // freeze the wave behind it forever. It simply never shows.
              console.warn(`splat ${i} (${splats[i].label}) failed to load`, err);
              arrived.add(i);
            },
          );
        });

        if (!assembling) {
          // No choreography to gate against — keep the settled behaviour, in
          // which a load failure surfaces as the room's error state.
          await Promise.all(meshes.map((m) => m.initialized));
          if (disposed) return;
        }
        setOutcome({ key, phase: "ready" });
        renderer.domElement.style.opacity = "1";

        // Cue lookups keyed by the index each cue addresses.
        const surfaceCue = new Map(plan.surfaces.map((c) => [c.index, c]));
        const objectCue = new Map(plan.objects.map((c) => [c.index, c]));
        const firedSteps = new Set<number>();
        let captionsDoneFired = false;
        let revealDoneFired = !assembling;
        const revealT0 = performance.now();

        // --- Movement 1: the boundary contour. A pen traces the measured
        // floor perimeter; verticals rise at the corners; the top edge
        // closes the box. Plain three.js lines and points — no new
        // dependency, no CSP surface.
        const contourParts: Array<{
          object: InstanceType<typeof THREE.Object3D>;
          material: { opacity: number; dispose(): void };
          geometry: { dispose(): void };
          baseOpacity: number;
        }> = [];
        let drawContour: ((now: number) => void) | null = null;

        if (assembling && plan.contour) {
          const c = plan.contour;
          const loopLengths = pathLengths(c.loop);
          const perimeter = loopLengths[loopLengths.length - 1];

          /** A progressively drawn polyline: complete vertices plus an
           * exact fractional tip, so the line grows smoothly instead of
           * stepping corner to corner. */
          const makeTracedLine = (path: typeof c.loop, opacity: number) => {
            const lengths = pathLengths(path);
            const total = lengths[lengths.length - 1];
            const geometry = new THREE.BufferGeometry();
            const positions = new Float32Array(path.length * 3);
            geometry.setAttribute(
              "position",
              new THREE.BufferAttribute(positions, 3),
            );
            const material = new THREE.LineBasicMaterial({
              color: CONTOUR_COLOR,
              transparent: true,
              opacity,
              depthWrite: false,
            });
            const line = new THREE.Line(geometry, material);
            line.visible = false;
            scene.add(line);
            contourParts.push({
              object: line,
              material,
              geometry,
              baseOpacity: opacity,
            });
            return (progress: number) => {
              if (progress <= 0 || total <= 0) {
                line.visible = false;
                return;
              }
              line.visible = true;
              const { point, segment } = pathPointAt(
                path,
                lengths,
                total * progress,
              );
              for (let i = 0; i <= segment; i++) {
                positions[i * 3] = path[i][0];
                positions[i * 3 + 1] = path[i][1];
                positions[i * 3 + 2] = path[i][2];
              }
              positions[(segment + 1) * 3] = point[0];
              positions[(segment + 1) * 3 + 1] = point[1];
              positions[(segment + 1) * 3 + 2] = point[2];
              geometry.setDrawRange(0, segment + 2);
              geometry.attributes.position.needsUpdate = true;
            };
          };

          const drawFloorLoop = makeTracedLine(c.loop, CONTOUR_FLOOR_OPACITY);
          const drawTopLoop = c.topLoop
            ? makeTracedLine(c.topLoop, CONTOUR_EDGE_OPACITY)
            : null;

          // Risers grow together — the room standing up, not a queue.
          let drawRisers: ((progress: number) => void) | null = null;
          if (c.risers.length > 0) {
            const geometry = new THREE.BufferGeometry();
            const positions = new Float32Array(c.risers.length * 6);
            c.risers.forEach((r, i) => {
              positions[i * 6] = r.from[0];
              positions[i * 6 + 1] = r.from[1];
              positions[i * 6 + 2] = r.from[2];
            });
            geometry.setAttribute(
              "position",
              new THREE.BufferAttribute(positions, 3),
            );
            const material = new THREE.LineBasicMaterial({
              color: CONTOUR_COLOR,
              transparent: true,
              opacity: CONTOUR_EDGE_OPACITY,
              depthWrite: false,
            });
            const segs = new THREE.LineSegments(geometry, material);
            segs.visible = false;
            scene.add(segs);
            contourParts.push({
              object: segs,
              material,
              geometry,
              baseOpacity: CONTOUR_EDGE_OPACITY,
            });
            drawRisers = (progress: number) => {
              segs.visible = progress > 0;
              c.risers.forEach((r, i) => {
                positions[i * 6 + 3] = r.from[0] + (r.to[0] - r.from[0]) * progress;
                positions[i * 6 + 4] = r.from[1] + (r.to[1] - r.from[1]) * progress;
                positions[i * 6 + 5] = r.from[2] + (r.to[2] - r.from[2]) * progress;
              });
              geometry.attributes.position.needsUpdate = true;
            };
          }

          // The pen itself: dots riding at and just behind the tip.
          const dotGeometry = new THREE.BufferGeometry();
          const dotPositions = new Float32Array(CONTOUR_DOT_COUNT * 3);
          dotGeometry.setAttribute(
            "position",
            new THREE.BufferAttribute(dotPositions, 3),
          );
          const dotMaterial = new THREE.PointsMaterial({
            color: CONTOUR_DOT_COLOR,
            size: CONTOUR_DOT_SIZE_PX,
            sizeAttenuation: false,
            transparent: true,
            opacity: 1,
            depthWrite: false,
          });
          const dots = new THREE.Points(dotGeometry, dotMaterial);
          dots.visible = false;
          scene.add(dots);
          contourParts.push({
            object: dots,
            material: dotMaterial,
            geometry: dotGeometry,
            baseOpacity: 1,
          });

          drawContour = (now: number) => {
            const t = now - revealT0;
            const loopP = settleEase(windowProgress(t, c.startMs, c.drawMs));
            drawFloorLoop(loopP);
            drawRisers?.(
              settleEase(windowProgress(t, c.riserStartMs, c.riserDrawMs)),
            );
            drawTopLoop?.(
              settleEase(windowProgress(t, c.topStartMs, c.topDrawMs)),
            );

            // Dots ride the tip while the perimeter draws, then retire.
            const penning = loopP > 0 && loopP < 1;
            dots.visible = penning;
            if (penning) {
              const tipS = perimeter * loopP;
              for (let i = 0; i < CONTOUR_DOT_COUNT; i++) {
                const { point } = pathPointAt(
                  c.loop,
                  loopLengths,
                  tipS - i * CONTOUR_DOT_SPACING * perimeter,
                );
                dotPositions[i * 3] = point[0];
                dotPositions[i * 3 + 1] = point[1];
                dotPositions[i * 3 + 2] = point[2];
              }
              dotGeometry.attributes.position.needsUpdate = true;
            }

            // The measurement hands off to the material.
            const fade = settleEase(windowProgress(t, c.fadeStartMs, c.fadeMs));
            for (const part of contourParts) {
              part.material.opacity = part.baseOpacity * (1 - fade);
              if (fade >= 1) part.object.visible = false;
            }
            if (fade >= 1) drawContour = null;
          };
        }

        // --- Movement 2: surfaces materialize in place. During the ramp
        // the material is transparent and does NOT write depth, so a
        // half-present surface never occludes anything; on completion it
        // is restored to the exact configuration decision 0066's depth
        // probe proved composites with Spark splats.
        if (assembling) {
          shellMeshes.forEach(({ mesh, extras }, i) => {
            if (!surfaceCue.has(i)) return;
            for (const o of [mesh, ...extras]) {
              o.visible = false;
              const m = o.material as InstanceType<
                typeof THREE.MeshStandardMaterial
              >;
              m.transparent = true;
              m.depthWrite = false;
              m.opacity = 0;
            }
          });
          for (const { index } of plan.objects) {
            meshes[index].visible = false;
            meshes[index].opacity = 0;
          }
        } else if (revealRef.current && !disposed) {
          // Reveal requested but not animated: the room is simply there.
          revealDoneRef.current?.();
        }

        // --- Entrance: a short dolly-in from farther out, interruptible by
        // the first grab. Runs on an eased clock inside the render loop.
        const ENTRANCE_MS = 1400;
        let entranceStart: number | null = performance.now();
        const fromOffset = finalOffset.clone().multiplyScalar(1.3).add(
          new THREE.Vector3(0, fitDistance * 0.12, 0),
        );
        const cancelEntrance = () => {
          entranceStart = null;
        };
        renderer.domElement.addEventListener("pointerdown", cancelEntrance);
        camera.position.copy(target).add(fromOffset);

        let raf = 0;
        const renderLoop = () => {
          raf = requestAnimationFrame(renderLoop);
          const now = performance.now();
          if (entranceStart !== null) {
            const t = Math.min(1, (now - entranceStart) / ENTRANCE_MS);
            const eased = 1 - Math.pow(1 - t, 3);
            camera.position
              .copy(target)
              .add(fromOffset.clone().lerp(finalOffset, eased));
            if (t >= 1) entranceStart = null;
          }
          // The contour outlives `done` — its hand-off fade is longer than
          // the closing beat — so it runs on its own until it retires.
          if (assembling) drawContour?.(now);
          if (assembling && !revealDoneFired) {
            const t = now - revealT0;
            // The object wave stretches for bytes; the surfaces never do,
            // because they are measured geometry and already here.
            objectHoldMs = revealHoldMs({
              objects: plan.objects,
              isReady: (i) => arrived.has(i),
              t,
              delayMs: objectHoldMs,
            });
            const objT = t - objectHoldMs;

            // Surfaces: fade up in place. No translation, ever.
            for (const [i, cue] of surfaceCue) {
              const p = settleEase(windowProgress(t, cue.startMs, cue.durationMs));
              const { mesh, extras } = shellMeshes[i];
              for (const o of [mesh, ...extras]) {
                if (p <= 0) {
                  o.visible = false;
                  continue;
                }
                o.visible = true;
                const m = o.material as InstanceType<
                  typeof THREE.MeshStandardMaterial
                >;
                if (p >= 1) {
                  if (m.transparent) {
                    m.transparent = false;
                    m.depthWrite = true;
                    m.opacity = 1;
                    m.needsUpdate = true;
                  }
                } else {
                  m.opacity = p;
                }
              }
            }

            // Pieces: settle from rest to rest, present before still.
            // Placement is read LIVE (splatsRef) — a piece proposed away
            // mid-wave settles into the place it is now going, never the
            // one this closure was built with.
            for (const [i, cue] of objectCue) {
              const raw = windowProgress(objT, cue.startMs, cue.durationMs);
              const mesh = meshes[i];
              const live = splatsRef.current[i] ?? splats[i];
              if (raw <= 0 || live.hidden) {
                mesh.visible = false;
                continue;
              }
              if (!firedSteps.has(i)) {
                firedSteps.add(i);
                mesh.visible = true;
                if (cue.named) revealStepRef.current?.(i, live.label);
              }
              const eased = settleEase(raw);
              mesh.position.y = live.position[1] + SETTLE_DROP_M * (1 - eased);
              mesh.opacity = settleEase(Math.min(1, raw / SETTLE_FADE_FRACTION));
            }

            // Both closing beats belong to the object wave, so they ride its
            // clock — the guest must not speak over a room still arriving.
            if (!captionsDoneFired && objT >= plan.captionsDoneMs) {
              captionsDoneFired = true;
              revealCaptionsDoneRef.current?.();
            }
            if (objT >= plan.doneMs) {
              revealDoneFired = true;
              // The wave has finished speaking: visibility goes back to the
              // placement seam, and any proposal that landed during the
              // reveal takes effect on this frame.
              revealOwnsVisibilityRef.current = false;
              applyLivePlacements(meshesRef.current, splatsRef.current, false);
              revealDoneRef.current?.();
            }
          }
          controls.update();
          renderer.render(scene, camera);
        };
        renderLoop();

        const onResize = () => {
          const w = container.clientWidth;
          const h = container.clientHeight;
          camera.aspect = w / h;
          camera.updateProjectionMatrix();
          renderer.setSize(w, h);
        };
        const resizeObserver = new ResizeObserver(onResize);
        resizeObserver.observe(container);

        cleanup = () => {
          cancelAnimationFrame(raf);
          if (idleTimer !== undefined) clearTimeout(idleTimer);
          resizeObserver.disconnect();
          renderer.domElement.removeEventListener("pointerdown", onGrab);
          renderer.domElement.removeEventListener("pointerup", onRelease);
          renderer.domElement.removeEventListener("pointerdown", cancelEntrance);
          controls.dispose();
          meshesRef.current = [];
          sceneRef.current = null;
          revealOwnsVisibilityRef.current = false;
          for (const m of meshes) {
            scene.remove(m);
            m.dispose?.();
          }
          for (const { object, material, geometry } of contourParts) {
            scene.remove(object);
            geometry.dispose();
            material.dispose();
          }
          for (const { mesh, extras } of shellMeshes) {
            for (const extra of extras) {
              scene.remove(extra);
              extra.geometry.dispose();
              (extra.material as { dispose(): void }).dispose();
            }
            scene.remove(mesh);
            mesh.geometry.dispose();
            mesh.material.dispose();
          }
          ground.geometry.dispose();
          (ground.material as { map?: { dispose(): void } }).map?.dispose();
          (ground.material as { dispose(): void }).dispose();
          renderer.dispose();
          renderer.domElement.remove();
        };
      } catch (exc) {
        if (!disposed) {
          setOutcome({
            key,
            phase: "error",
            error: exc instanceof Error ? exc.message : String(exc),
          });
        }
      }
    })();

    return () => {
      disposed = true;
      // Cleared here and not only inside `cleanup`, which is not assigned
      // until the build finishes: a build abandoned while its splats were
      // still loading must not leave the decoration effects drawing into a
      // scene nobody renders.
      sceneRef.current = null;
      meshesRef.current = [];
      cleanup?.();
    };
    // `key` is the signature of what this effect BUILDS — splat files,
    // clip volumes, shell planes — so the arrays those come from are
    // deliberately NOT dependencies. Depending on `splats` by identity
    // would restart the renderer whenever a caller recomputed the array,
    // which is exactly what a proposal does (0133). `outlines` and
    // `labels` are read here only to be handed to the decoration effects;
    // they must never appear in this list (0188).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, idleOrbit]);

  // The placement seam. Runs on every `splats` change and costs one matrix
  // write per piece; the renderer above is untouched.
  useEffect(() => {
    applyLivePlacements(
      meshesRef.current,
      splats,
      revealOwnsVisibilityRef.current,
    );
  }, [splats]);

  // --- The decoration effects (decision 0188). Each owns its own objects
  // end to end: it builds them into the live scene and takes exactly those
  // back out again. Nothing here can restart the renderer, which is the
  // entire point — an outline appearing is five vertices on the floor, and
  // it used to cost a re-download of the room.
  //
  // Both read the seam at run time and do nothing when there is no scene
  // yet; `sceneEpoch` brings them back when one is published. The seam is
  // captured in a local so the cleanup removes from the scene it added to,
  // never from whichever scene happens to be current later.
  useEffect(() => {
    const seam = sceneRef.current;
    if (!seam) return;
    const built = buildOutlines(seam, outlines ?? []);
    return () => {
      for (const d of built) {
        seam.scene.remove(d.object);
        d.dispose();
      }
    };
    // Keyed on the SIGNATURE, not the array identity — an equal-but-fresh
    // array from a re-rendering parent must cost nothing. Reading the array
    // itself is safe: an effect runs with the closure of the render whose
    // deps changed, and an unchanged signature means equal contents.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [outlineSig, sceneEpoch]);

  useEffect(() => {
    const seam = sceneRef.current;
    if (!seam) return;
    const built = buildLabels(seam, labels ?? []);
    return () => {
      for (const d of built) {
        seam.scene.remove(d.object);
        d.dispose();
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [labelSig, sceneEpoch]);

  return (
    <div
      className={`relative overflow-hidden ${
        frameless ? "" : "rounded-xl border border-ink/15"
      } ${className ?? ""}`}
      style={{
        // The stage's atmosphere: warm lamplight dark (the palette's
        // ambient register — §11's family, dimmed). CSS, not clear-color,
        // so it can be a gradient.
        background:
          "radial-gradient(120% 90% at 50% 42%, #36342f 0%, #23221e 55%, #181715 100%)",
      }}
    >
      <div ref={containerRef} className="absolute inset-0" />
      {/* Vignette — pulls the eye to the room, softens the frame edges. */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0"
        style={{ boxShadow: "inset 0 0 110px 32px rgba(18, 12, 6, 0.5)" }}
      />
      {phase === "loading" && (
        <Overlay>
          <p className="animate-pulse text-sm text-paper/60">Assembling the room…</p>
        </Overlay>
      )}
      {phase === "empty" && (
        <Overlay>
          <p className="text-sm text-paper/45">Nothing to render yet.</p>
        </Overlay>
      )}
      {phase === "error" && (
        <Overlay>
          <div className="max-w-sm text-center">
            <p className="text-sm font-medium text-[#e0a9a1]">Viewer error</p>
            <p className="mt-1 break-words text-xs text-paper/50">{error}</p>
          </div>
        </Overlay>
      )}
    </div>
  );
}

function Overlay({ children }: { children: React.ReactNode }) {
  return (
    <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
      {children}
    </div>
  );
}
