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
  return (
    <p
      className={`font-serif italic leading-relaxed ${
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

/**
 * The composer's silhouette, shipped disabled and saying so. Stage-1
 * conversation has no backend yet; this reserves the composer's place in
 * the layout (design §3/§5) without pretending to listen — the resting
 * text explains itself, and nothing here is focusable or submittable.
 */
export function DisabledComposer({ className }: { className?: string }) {
  return (
    <div
      className={`flex items-center gap-3 rounded-full bg-white/95 py-3 pl-5 pr-3 opacity-80 shadow-float ${className ?? ""}`}
    >
      <span className="min-w-0 flex-1 truncate text-sm text-ink/40">
        The guest hasn&rsquo;t arrived yet — this is where you&rsquo;ll talk.
      </span>
      <span
        aria-hidden
        className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-ink/10 font-semibold text-ink/30"
      >
        ↑
      </span>
    </div>
  );
}
