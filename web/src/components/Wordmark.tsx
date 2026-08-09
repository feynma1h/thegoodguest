/**
 * The product wordmark — isolated here because NO NAME HAS BEEN CHOSEN.
 * "roomstudio" is a stand-in (see CLAUDE.md "Naming" and decision 0055).
 * The design file renders every wordmark slot as a literal placeholder
 * ("❖ WORDMARK" in quiet tracked mono); this component honors that —
 * visibly a stand-in, deliberately quiet, because the room is the hero.
 *
 * This is the only place the name is RENDERED AS THE MARK, but it is not the
 * only place the string appears in user-visible text. When the real name
 * lands, also update: app/layout.tsx (the tab title), and app/terms/page.tsx
 * and app/privacy/page.tsx (titles, descriptions, and body copy, including the
 * "working title" sentence in Terms §2, which stops being true). The
 * "roomstudio:"-prefixed localStorage keys in app/page.tsx, lib/seen.ts, and
 * components/NewRoomSheet.tsx are internal and can stay — renaming them
 * silently resets returning visitors.
 */

export default function Wordmark({
  className,
  tone = "ink",
}: {
  className?: string;
  tone?: "ink" | "cream";
}) {
  return (
    <span
      className={`inline-flex items-baseline gap-1.5 font-mono text-[10.5px] font-medium uppercase tracking-[0.16em] ${
        tone === "cream" ? "text-paper/70" : "text-ink/70"
      } ${className ?? ""}`}
    >
      <span aria-hidden>❖</span>
      roomstudio
    </span>
  );
}
