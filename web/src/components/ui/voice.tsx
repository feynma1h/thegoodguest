/**
 * The Good Guest voice primitives (design file: "Good Guest — Product
 * System"; decision 0057). Two registers used everywhere, so the voice
 * stays one voice:
 *
 *   GuestLine — the guest speaking: italic serif, warm ink. Reserved for
 *     lines written in the guest's first person; UI copy stays sans.
 *   Eyebrow — quiet mono section label, uppercase-tracked. Labels a zone;
 *     never a sentence.
 *
 * `tone="cream"` flips either for dark ink panels (thresholds, terminal
 * failure, footer strips).
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
        tone === "cream" ? "text-paper" : "text-ink"
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
      className={`font-mono text-[10px] font-medium uppercase tracking-[0.14em] ${
        tone === "cream" ? "text-paper/55" : "text-ink/50"
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
