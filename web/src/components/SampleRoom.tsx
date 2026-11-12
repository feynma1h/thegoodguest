"use client";

/**
 * A stage for the landing's sample room. It loads three.js on demand and
 * mounts components/sampleRoomScene.ts on its canvas; the parent steers it
 * through the handle (views, stage, mode, pieces taken out).
 *
 * This is the second three.js entry point after SplatViewer, and the only one
 * that never draws a person's room (decision 0361). Options are read once,
 * at mount; later changes go through the handle, so a re-render never
 * rebuilds the scene.
 */

import { useEffect, useImperativeHandle, useRef, useState } from "react";

import type { SampleRoomHandle, SampleRoomOptions } from "@/components/sampleRoomScene";

export type { SampleRoomHandle } from "@/components/sampleRoomScene";

export default function SampleRoom({
  ref,
  label,
  className,
  onView,
  ...options
}: Omit<SampleRoomOptions, "onView"> & {
  ref?: React.Ref<SampleRoomHandle>;
  label: string;
  className?: string;
  onView?: (view: number) => void;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const handleRef = useRef<SampleRoomHandle | null>(null);
  const onViewRef = useRef(onView);
  const initial = useRef(options);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    onViewRef.current = onView;
  }, [onView]);

  useImperativeHandle(
    ref,
    () => ({
      setMode: (m) => handleRef.current?.setMode(m),
      setStage: (s) => handleRef.current?.setStage(s),
      setRemoved: (ids) => handleRef.current?.setRemoved(ids),
      replay: (to) => handleRef.current?.replay(to),
      goTo: (v) => handleRef.current?.goTo(v),
      dispose: () => handleRef.current?.dispose(),
    }),
    [],
  );

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    let disposed = false;
    (async () => {
      try {
        const [THREE, { OrbitControls }, { RoundedBoxGeometry }, { RoomEnvironment }, { mountSampleRoom }] =
          await Promise.all([
            import("three"),
            import("three/addons/controls/OrbitControls.js"),
            import("three/addons/geometries/RoundedBoxGeometry.js"),
            import("three/addons/environments/RoomEnvironment.js"),
            import("@/components/sampleRoomScene"),
          ]);
        if (disposed) return;
        handleRef.current = mountSampleRoom({ THREE, OrbitControls, RoundedBoxGeometry, RoomEnvironment }, canvas, {
          ...initial.current,
          onView: (v) => onViewRef.current?.(v),
        });
      } catch {
        // No WebGL: the stage keeps its own ground, and the page still reads.
        if (!disposed) setFailed(true);
      }
    })();
    return () => {
      disposed = true;
      handleRef.current?.dispose();
      handleRef.current = null;
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      role="img"
      aria-label={label}
      data-failed={failed || undefined}
      className={`block h-full w-full touch-pan-y ${failed ? "invisible" : "cursor-grab active:cursor-grabbing"} ${className ?? ""}`}
    />
  );
}
