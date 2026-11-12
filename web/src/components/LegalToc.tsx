"use client";

/**
 * The legal pages' side list (decision 0361): every section, with the one
 * being read marked as current. Rendered on the server like the rest of the
 * document; the marking is the only part that needs the browser.
 */

import { useEffect, useState } from "react";

export default function LegalToc({
  sections,
}: {
  sections: { id: string; title: string }[];
}) {
  const [current, setCurrent] = useState<string | null>(sections[0]?.id ?? null);

  useEffect(() => {
    const els = sections
      .map((s) => document.getElementById(s.id))
      .filter((el): el is HTMLElement => el !== null);
    if (els.length === 0) return;
    // The current section is the last one whose top has passed the upper
    // third of the window.
    const pick = () => {
      const line = window.innerHeight * 0.33;
      let id = els[0].id;
      for (const el of els) {
        if (el.getBoundingClientRect().top <= line) id = el.id;
      }
      setCurrent(id);
    };
    // A page opened at an anchor starts part-way down.
    const first = window.requestAnimationFrame(pick);
    window.addEventListener("scroll", pick, { passive: true });
    window.addEventListener("resize", pick);
    return () => {
      window.cancelAnimationFrame(first);
      window.removeEventListener("scroll", pick);
      window.removeEventListener("resize", pick);
    };
  }, [sections]);

  return (
    <nav
      aria-label="On this page"
      className="sticky top-28 hidden border-t border-ink/10 pt-3.5 lg:block"
    >
      {sections.map((s) => (
        <a
          key={s.id}
          href={`#${s.id}`}
          aria-current={current === s.id ? "true" : undefined}
          className={`block py-[7px] text-[14.5px] leading-snug transition-colors hover:text-ink ${
            current === s.id ? "text-ink" : "text-ink-2"
          }`}
        >
          {s.title}
        </a>
      ))}
    </nav>
  );
}
