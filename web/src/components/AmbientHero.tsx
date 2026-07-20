"use client";

/**
 * The landing hero's ambient light field — a reduced form of the founding
 * draft's Act 1 ("the cursor is a soft light source; the room is
 * desaturated by default, color only exists where the user looks").
 *
 * Pure CSS layers driven by two custom properties (--mx/--my): a neutral
 * near-black base with a faint horizon and floor grid, and warm-white
 * room light revealed around the cursor. Per decision 0056 the warmth
 * here is CONTENT (light falling in a room — the product itself), not
 * chrome decoration; the UI around it stays achromatic. Cursor position
 * is eased on rAF so the light feels weighted rather than glued to the
 * pointer. Honors prefers-reduced-motion by holding a fixed glow.
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
      {/* Base: neutral room tone with a faint horizon. */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0"
        style={{
          background:
            "linear-gradient(to bottom, #0a0a0a 0%, #0c0c0c 55%, #101010 68%, #0a0a0a 100%)",
        }}
      />
      {/* Floor grid, fading toward the horizon. */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 bottom-0 h-[45%] opacity-[0.1]"
        style={{
          background:
            "repeating-linear-gradient(to right, transparent 0 calc(6.25% - 1px), #8a8a8a calc(6.25% - 1px) 6.25%)," +
            "repeating-linear-gradient(to top, transparent 0 34px, #8a8a8a 34px 35px)",
          maskImage:
            "linear-gradient(to top, rgba(0,0,0,0.9), transparent 90%)",
          WebkitMaskImage:
            "linear-gradient(to top, rgba(0,0,0,0.9), transparent 90%)",
          transform: "perspective(600px) rotateX(55deg)",
          transformOrigin: "bottom",
        }}
      />
      {/* Warm-white room light — content, not chrome. */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0"
        style={{
          background:
            "radial-gradient(52rem 36rem at var(--mx) var(--my), rgba(255,244,228,0.09), rgba(255,236,214,0.04) 45%, transparent 70%)",
        }}
      />
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 mix-blend-screen"
        style={{
          background:
            "radial-gradient(18rem 13rem at var(--mx) var(--my), rgba(255,248,238,0.07), transparent 70%)",
        }}
      />
      <div className="relative">{children}</div>
    </div>
  );
}
