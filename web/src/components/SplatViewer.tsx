"use client";

/**
 * SplatViewer — the ONLY module in this app that touches the rendering
 * library. Everything else speaks PositionedSplat (lib/api/types.ts):
 * "a splat file URL plus a world transform". Swapping Spark for another
 * renderer is a rewrite of this file and nothing else — keep it that way.
 *
 * Renderer: three.js + @sparkjsdev/spark (WebGL2 3DGS renderer; decided
 * over WebGPU-first options — see the session's decision note). Both are
 * imported dynamically inside useEffect so the static export never
 * evaluates GPU/browser globals at build time.
 *
 * Coordinate frames: PositionedSplat transforms are ARKit-world (right-
 * handed, +Y up, meters) — the same handedness and up-axis as three.js,
 * so transforms apply directly with no basis change.
 */

import { useEffect, useMemo, useRef, useState } from "react";

import type { PositionedSplat } from "@/lib/api/types";

interface SplatViewerProps {
  splats: PositionedSplat[];
  className?: string;
}

/** Async-only load outcome, stamped with the splat-set key it belongs to.
 * "Loading" is derived (no outcome for the current key yet) so effects
 * never call setState synchronously (react-hooks/set-state-in-effect). */
type LoadOutcome = { key: string; phase: "ready" } | { key: string; phase: "error"; error: string };

export default function SplatViewer({ splats, className }: SplatViewerProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const key = useMemo(
    () => splats.map((s) => `${s.url}@${s.position.join(",")}`).join("|"),
    [splats],
  );
  const [outcome, setOutcome] = useState<LoadOutcome | null>(null);

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

        const renderer = new THREE.WebGLRenderer({ antialias: false });
        renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
        renderer.setSize(container.clientWidth, container.clientHeight);
        container.appendChild(renderer.domElement);

        const scene = new THREE.Scene();
        scene.background = new THREE.Color(0x0d0c0a);

        const camera = new THREE.PerspectiveCamera(
          55,
          container.clientWidth / container.clientHeight,
          0.02,
          100,
        );
        camera.position.set(2.6, 1.9, 2.6);

        const spark = new SparkRenderer({ renderer });
        scene.add(spark);

        // Subtle stage: a floor grid so scale and gravity read instantly.
        const grid = new THREE.GridHelper(10, 20, 0x35302a, 0x211d18);
        scene.add(grid);

        const controls = new OrbitControls(camera, renderer.domElement);
        controls.enableDamping = true;
        controls.dampingFactor = 0.08;

        const meshes = splats.map((s) => {
          const mesh = new SplatMesh({ url: s.url });
          mesh.position.set(...s.position);
          mesh.quaternion.set(...s.rotation_xyzw);
          mesh.scale.setScalar(s.scale);
          scene.add(mesh);
          return mesh;
        });

        // Aim the camera at the centroid of the placed objects.
        const centroid = splats
          .reduce(
            (acc, s) => acc.add(new THREE.Vector3(...s.position)),
            new THREE.Vector3(),
          )
          .divideScalar(splats.length);
        controls.target.copy(centroid);

        await Promise.all(meshes.map((m) => m.initialized));
        if (disposed) return;
        setOutcome({ key, phase: "ready" });

        let raf = 0;
        const renderLoop = () => {
          raf = requestAnimationFrame(renderLoop);
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
          resizeObserver.disconnect();
          controls.dispose();
          for (const m of meshes) {
            scene.remove(m);
            m.dispose?.();
          }
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
  }, [key, splats]);

  return (
    <div
      className={`relative overflow-hidden rounded-2xl border border-white/[0.06] bg-[#0d0c0a] ${className ?? ""}`}
    >
      <div ref={containerRef} className="absolute inset-0" />
      {phase === "loading" && (
        <Overlay>
          <p className="animate-pulse text-sm text-zinc-400">Loading scene…</p>
        </Overlay>
      )}
      {phase === "empty" && (
        <Overlay>
          <p className="text-sm text-zinc-500">Nothing to render yet.</p>
        </Overlay>
      )}
      {phase === "error" && (
        <Overlay>
          <div className="max-w-sm text-center">
            <p className="text-sm font-medium text-red-400">Viewer error</p>
            <p className="mt-1 break-words text-xs text-zinc-500">{error}</p>
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
