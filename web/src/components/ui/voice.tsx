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
