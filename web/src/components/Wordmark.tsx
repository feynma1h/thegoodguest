/**
 * The product wordmark — isolated here because NO NAME HAS BEEN CHOSEN.
 * "roomstudio" is a stand-in (see CLAUDE.md "Naming" and decision 0055).
 * When the real name lands, this file is the only UI change.
 */

export default function Wordmark({ className }: { className?: string }) {
  return (
    <span className={`text-[15px] font-semibold tracking-tight ${className ?? ""}`}>
      roomstudio
    </span>
  );
}
