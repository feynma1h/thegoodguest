/**
 * The product wordmark — isolated here because NO NAME HAS BEEN CHOSEN.
 * "roomstudio" is a stand-in (see CLAUDE.md "Naming" and decision 0055).
 * When the real name lands, this file is the only UI change.
 */

export default function Wordmark({ className }: { className?: string }) {
  return (
    <span className={`font-serif text-[17px] font-medium tracking-tight ${className ?? ""}`}>
      roomstudio<span className="text-accent">.</span>
    </span>
  );
}
