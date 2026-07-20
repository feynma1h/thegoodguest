"use client";

/**
 * The landing hero's ambient light field — a reduced form of the founding
 * draft's Act 1 ("the cursor is a soft light source; the room is
 * desaturated by default, color only exists where the user looks").
 *
 * Pure CSS layers driven by two custom properties (--mx/--my): a dark
 * room-toned base with a faint horizon and floor grid, and a warm color
 * layer revealed through a radial mask centered on the cursor. Cursor
 * position is eased toward its target on rAF so the light feels weighted
 * rather than glued to the pointer. Honors prefers-reduced-motion by
 * holding a fixed, centered glow.
 */

import { useEffect, useRef } from "react";

export default function AmbientHero({ children }: { children: React.ReactNode }) {
  const ref = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

    let raf = 0;
    const target = { x: 0.5, y: 0.42 };
    const pos = { ...target };

    const onMove = (e: PointerEvent) => {
      const r = el.getBoundingClientRect();
      target.x = (e.clientX - r.left) / r.width;
      target.y = (e.clientY - r.top) / r.height;
    };

    const tick = () => {
      // Weighted follow — the light trails the cursor like it has mass.
      pos.x += (target.x - pos.x) * 0.07;
      pos.y += (target.y - pos.y) * 0.07;
      el.style.setProperty("--mx", `${(pos.x * 100).toFixed(2)}%`);
      el.style.setProperty("--my", `${(pos.y * 100).toFixed(2)}%`);
      raf = requestAnimationFrame(tick);
    };

    el.addEventListener("pointermove", onMove);
    raf = requestAnimationFrame(tick);
    return () => {
      el.removeEventListener("pointermove", onMove);
      cancelAnimationFrame(raf);
    };
  }, []);

  return (
    <div
      ref={ref}
      className="relative overflow-hidden"
      style={{ "--mx": "50%", "--my": "42%" } as React.CSSProperties}
    >
      {/* Base: near-black room tone with a faint horizon. */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0"
        style={{
          background:
            "linear-gradient(to bottom, #0b0a09 0%, #0d0c0a 55%, #12100c 68%, #0b0a09 100%)",
        }}
      />
      {/* Floor grid, fading toward the horizon. */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 bottom-0 h-[45%] opacity-[0.13]"
        style={{
          background:
            "repeating-linear-gradient(to right, transparent 0 calc(6.25% - 1px), #a08c6c calc(6.25% - 1px) 6.25%)," +
            "repeating-linear-gradient(to top, transparent 0 34px, #a08c6c 34px 35px)",
          maskImage:
            "linear-gradient(to top, rgba(0,0,0,0.9), transparent 90%)",
          WebkitMaskImage:
            "linear-gradient(to top, rgba(0,0,0,0.9), transparent 90%)",
          transform: "perspective(600px) rotateX(55deg)",
          transformOrigin: "bottom",
        }}
      />
      {/* Color exists only where the light is. */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0"
        style={{
          background:
            "radial-gradient(52rem 36rem at var(--mx) var(--my), rgba(224,163,92,0.16), rgba(190,120,70,0.07) 45%, transparent 70%)",
        }}
      />
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 mix-blend-screen"
        style={{
          background:
            "radial-gradient(20rem 14rem at var(--mx) var(--my), rgba(255,214,160,0.10), transparent 70%)",
        }}
      />
      <div className="relative">{children}</div>
    </div>
  );
}
