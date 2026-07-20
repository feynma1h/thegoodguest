/**
 * The product wordmark — isolated here because NO NAME HAS BEEN CHOSEN.
 * "roomstudio" is a stand-in (see CLAUDE.md "Naming" and decision 0055).
 * The design file renders every wordmark slot as a literal placeholder
 * ("❖ WORDMARK" in quiet tracked mono); this component honors that —
 * visibly a stand-in, deliberately quiet, because the room is the hero.
 * When the real name lands, this file is the only UI change.
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
