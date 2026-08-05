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
 * Reveal (design §4 + decision 0066): with `reveal`, the shell arrives
 * first — floor, then walls, the stage standing up — and then objects
 * one at a time, largest first, each dropping softly into place;
 * `onRevealStep` fires as each object arrives (the DOM layer names it)
 * and `onRevealDone` when the room is assembled. Without a shell the
 * objects assemble on the honest grid, as before. Reduced motion
 * collapses everything to an immediate full room.
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
import { openingRect, projectToWallPlane, wallFrame } from "@/lib/shell3d";

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
  /** Play the objects-first assembly on load. */
  reveal?: boolean;
  onRevealStep?: (index: number, label: string) => void;
  onRevealDone?: () => void;
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

// Assembly timing: object i starts at REVEAL_LEAD + i*REVEAL_STEP and
// settles over REVEAL_DROP_MS from REVEAL_DROP_M above its place.
const REVEAL_LEAD_MS = 500;
const REVEAL_STEP_MS = 650;
const REVEAL_DROP_MS = 700;
const REVEAL_DROP_M = 0.4;
// Shell staging (0066: the shell is the stage — floor, then walls, then
// the objects): floor appears at REVEAL_LEAD, each wall SHELL_WALL_STEP
// later, and the object assembly starts a beat after the last wall.
const SHELL_FLOOR_MS = 600;
const SHELL_WALL_STEP_MS = 350;

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
  onRevealDone,
}: SplatViewerProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const key = useMemo(
    () =>
      splats.map((s) => `${s.url}@${s.position.join(",")}`).join("|") +
      "|shell:" +
      (shell
        ?.map((p) => `${p.kind}:${p.material.albedo_hex ?? "-"}:${p.corners.length}`)
        .join(",") ?? "none"),
    [splats, shell],
  );
  const [outcome, setOutcome] = useState<LoadOutcome | null>(null);

  // Callback identity must not restart the renderer; refs are written
  // after commit (never during render) and read at call time.
  const revealStepRef = useRef(onRevealStep);
  const revealDoneRef = useRef(onRevealDone);
  useEffect(() => {
    revealStepRef.current = onRevealStep;
    revealDoneRef.current = onRevealDone;
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
        const [THREE, { OrbitControls }, { SparkRenderer, SplatMesh }] =
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

        const meshes = splats.map((s) => {
          const mesh = new SplatMesh({ url: s.url });
          mesh.position.set(...s.position);
          mesh.quaternion.set(...s.rotation_xyzw);
          mesh.scale.setScalar(s.scale);
          scene.add(mesh);
          return mesh;
        });

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
              centroid.distanceTo(new THREE.Vector3(...s.position)) + s.scale * 1.2,
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

        await Promise.all(meshes.map((m) => m.initialized));
        if (disposed) return;
        setOutcome({ key, phase: "ready" });
        renderer.domElement.style.opacity = "1";

        // --- Assembly (design §4, extended by 0066): the shell is the
        // stage — floor, then walls — then the largest pieces first, each
        // dropped softly onto it. Reduced motion skips straight to the
        // assembled room.
        const reducedMotion = window.matchMedia(
          "(prefers-reduced-motion: reduce)",
        ).matches;
        const assembling =
          reveal && !reducedMotion && (meshes.length > 0 || shellMeshes.length > 0);
        // Shell first: floor at the lead, each wall a step later; objects
        // begin a beat after the last wall (or at the lead when no shell).
        const shellOrder = [...shellMeshes].sort((a) =>
          a.plane.kind === "floor" ? -1 : 1,
        );
        const shellStartAt = new Map<number, number>(); // shell idx -> start ms
        const shellDelayMs =
          shellMeshes.length > 0
            ? SHELL_FLOOR_MS +
              shellOrder.filter((s) => s.plane.kind === "wall").length *
                SHELL_WALL_STEP_MS +
              250
            : 0;
        const revealOrder = splats
          .map((s, i) => ({ i, size: s.scale }))
          .sort((a, b) => b.size - a.size)
          .map((entry, seq) => ({ ...entry, seq }));
        const revealStartAt = new Map<number, number>(); // mesh idx -> start ms
        const revealFired = new Set<number>();
        let revealDoneFired = !assembling;
        const revealT0 = performance.now();
        if (assembling) {
          let wallSeq = 0;
          shellOrder.forEach((entry) => {
            const idx = shellMeshes.indexOf(entry);
            const at =
              entry.plane.kind === "floor"
                ? revealT0 + REVEAL_LEAD_MS
                : revealT0 +
                  REVEAL_LEAD_MS +
                  SHELL_FLOOR_MS +
                  wallSeq++ * SHELL_WALL_STEP_MS;
            shellStartAt.set(idx, at);
            entry.mesh.visible = false;
            for (const extra of entry.extras) extra.visible = false;
          });
          for (const { i, seq } of revealOrder) {
            revealStartAt.set(
              i,
              revealT0 + REVEAL_LEAD_MS + shellDelayMs + seq * REVEAL_STEP_MS,
            );
            meshes[i].visible = false;
          }
        } else if (reveal && !disposed) {
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
          if (assembling && !revealDoneFired) {
            let allSettled = true;
            for (const [i, startMs] of shellStartAt) {
              if (now >= startMs) {
                shellMeshes[i].mesh.visible = true;
                for (const extra of shellMeshes[i].extras) extra.visible = true;
              } else {
                allSettled = false;
              }
            }
            for (const [i, startMs] of revealStartAt) {
              const p = (now - startMs) / REVEAL_DROP_MS;
              if (p < 0) {
                allSettled = false;
                continue;
              }
              const mesh = meshes[i];
              if (!revealFired.has(i)) {
                revealFired.add(i);
                mesh.visible = true;
                revealStepRef.current?.(i, splats[i].label);
              }
              if (p < 1) {
                allSettled = false;
                const eased = 1 - Math.pow(1 - Math.min(1, p), 3);
                mesh.position.y = splats[i].position[1] + REVEAL_DROP_M * (1 - eased);
              } else {
                mesh.position.y = splats[i].position[1];
              }
            }
            if (allSettled) {
              revealDoneFired = true;
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
          for (const m of meshes) {
            scene.remove(m);
            m.dispose?.();
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
      cleanup?.();
    };
  }, [key, splats, shell, idleOrbit, reveal]);

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
          "radial-gradient(120% 90% at 50% 42%, #3f3226 0%, #2a2017 55%, #1c1610 100%)",
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
            <p className="text-sm font-medium text-[#e8a68e]">Viewer error</p>
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
