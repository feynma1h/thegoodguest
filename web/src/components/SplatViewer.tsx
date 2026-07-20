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
 * Reveal (design §4, the objects-first assembly — literally our path,
 * since the room-shell pipeline is unbuilt): with `reveal`, objects
 * arrive one at a time onto the bare ground plane, largest first, each
 * dropping softly into place; `onRevealStep` fires as each arrives (the
 * DOM layer names it) and `onRevealDone` when the room is assembled.
 * Reduced motion collapses the assembly to an immediate full room.
 */

import { useEffect, useMemo, useRef, useState } from "react";

import type { PositionedSplat } from "@/lib/api/types";

interface SplatViewerProps {
  splats: PositionedSplat[];
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

export default function SplatViewer({
  splats,
  className,
  idleOrbit = false,
  frameless = false,
  reveal = false,
  onRevealStep,
  onRevealDone,
}: SplatViewerProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const key = useMemo(
    () => splats.map((s) => `${s.url}@${s.position.join(",")}`).join("|"),
    [splats],
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

  const phase: "empty" | "loading" | "ready" | "error" =
    splats.length === 0
      ? "empty"
      : outcome?.key === key
        ? outcome.phase
        : "loading";
  const error = outcome?.key === key && outcome.phase === "error" ? outcome.error : null;

  useEffect(() => {
    if (splats.length === 0) return;
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

        const ground = new THREE.Mesh(
          new THREE.PlaneGeometry(GROUND_SIZE, GROUND_SIZE),
          new THREE.MeshBasicMaterial({
            map: new THREE.CanvasTexture(makeGroundTexture()),
            transparent: true,
            depthWrite: false,
          }),
        );
        ground.rotation.x = -Math.PI / 2;
        scene.add(ground);

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
        // per-object scale as a proxy for size).
        const centroid = splats
          .reduce(
            (acc, s) => acc.add(new THREE.Vector3(...s.position)),
            new THREE.Vector3(),
          )
          .divideScalar(splats.length);
        const radius = Math.max(
          1.4,
          ...splats.map(
            (s) =>
              centroid.distanceTo(new THREE.Vector3(...s.position)) + s.scale * 1.2,
          ),
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

        // --- Assembly (design §4): largest pieces first, each dropped
        // softly onto the ground plane. Reduced motion skips straight to
        // the assembled room.
        const reducedMotion = window.matchMedia(
          "(prefers-reduced-motion: reduce)",
        ).matches;
        const assembling = reveal && !reducedMotion && meshes.length > 0;
        const revealOrder = splats
          .map((s, i) => ({ i, size: s.scale }))
          .sort((a, b) => b.size - a.size)
          .map((entry, seq) => ({ ...entry, seq }));
        const revealStartAt = new Map<number, number>(); // mesh idx -> start ms
        const revealFired = new Set<number>();
        let revealDoneFired = !assembling;
        const revealT0 = performance.now();
        if (assembling) {
          for (const { i, seq } of revealOrder) {
            revealStartAt.set(i, revealT0 + REVEAL_LEAD_MS + seq * REVEAL_STEP_MS);
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
  }, [key, splats, idleOrbit, reveal]);

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
