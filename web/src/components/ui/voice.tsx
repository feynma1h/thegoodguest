/**
 * The Good Guest voice primitives (decisions 0057 and 0361). Two registers
 * used everywhere, so the voice stays one voice:
 *
 *   GuestLine — the guest speaking: italic serif. Reserved for lines written
 *     in the guest's first person; interface copy stays sans.
 *   Eyebrow — a quiet zone label in the interface face, sentence case. It
 *     is never mono and never tracked capitals (decision 0361); mono is for
 *     measurements.
 *
 * `tone="cream"` flips either for the dusk register (thresholds, terminal
 * failure, the room page).
 */

export function GuestLine({
  children,
  tone = "ink",
  className,
}: {
  children: React.ReactNode;
  tone?: "ink" | "cream";
  className?: string;
}) {
  // A caller's own line height replaces the default rather than racing it:
  // two leading utilities on one element resolve by stylesheet order, not
  // by the order they are written in.
  const leading = /(^|\s)leading-/.test(className ?? "") ? "" : "leading-relaxed";
  return (
    <p
      className={`font-serif italic ${leading} ${
        tone === "cream" ? "text-on-dusk" : "text-ink"
      } ${className ?? ""}`}
    >
      {children}
    </p>
  );
}

export function Eyebrow({
  children,
  tone = "ink",
  className,
}: {
  children: React.ReactNode;
  tone?: "ink" | "cream";
  className?: string;
}) {
  return (
    <p
      className={`text-[13px] font-medium ${
        tone === "cream" ? "text-on-dusk-2" : "text-ink-2"
      } ${className ?? ""}`}
    >
      {children}
    </p>
  );
}
