/**
 * Typographic shell for the two legal documents (/privacy, /terms).
 *
 * These pages exist for two audiences that never meet: App Store review,
 * which needs a reachable URL, and a person who actually wants to know what
 * happens to a scan of their home. The second audience is the one the prose
 * is written for — every claim here is derived from what the code does, not
 * from a template, and where the system's behaviour is imperfect the document
 * says so rather than rounding up to a promise.
 *
 * Design: the Good Guest system (decision 0057) at reading width — serif for
 * the document voice, sans for structure, mono for the machine-checkable
 * facts (bucket names, retention windows, endpoints).
 */

import Link from "next/link";
import type { ReactNode } from "react";

/** A section heading with a mono eyebrow — the document's spine. */
export function Section({
  n,
  title,
  children,
}: {
  n: string;
  title: string;
  children: ReactNode;
}) {
  return (
    <section className="mt-10 scroll-mt-20">
      <h2 className="flex items-baseline gap-3 text-[17px] font-semibold text-ink">
        <span className="font-mono text-[11px] text-ink/40">{n}</span>
        {title}
      </h2>
      <div className="mt-3 space-y-3 text-[15px] leading-relaxed text-ink/75">
        {children}
      </div>
    </section>
  );
}

/** Machine data inline — bucket names, windows, endpoints. */
export function M({ children }: { children: ReactNode }) {
  return <code className="font-mono text-[0.87em] text-ink/90">{children}</code>;
}

export default function LegalPage({
  title,
  updated,
  summary,
  children,
}: {
  title: string;
  updated: ReactNode;
  summary: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="mx-auto max-w-2xl px-6 pb-24 pt-12">
      <p className="font-mono text-[11px] uppercase tracking-[0.14em] text-ink/40">
        {title === "Privacy Policy" ? "What happens to your room" : "The agreement"}
      </p>
      <h1 className="mt-2 font-serif text-4xl text-ink">{title}</h1>
      <p className="mt-2 font-mono text-[11px] text-ink/45">Last updated {updated}</p>

      <div className="mt-7 rounded-2xl border border-ink/12 bg-parchment/60 px-5 py-4">
        <p className="font-serif text-[15px] italic leading-relaxed text-ink/80">
          {summary}
        </p>
      </div>

      {children}

      <hr className="mt-14 border-ink/10" />
      <div className="mt-5 flex items-center justify-between text-[13px]">
        <Link href="/" className="text-accent-deep transition-colors hover:text-ink">
          ← Back
        </Link>
        <div className="flex gap-4 text-ink/50">
          <Link href="/privacy" className="transition-colors hover:text-ink">
            Privacy
          </Link>
          <Link href="/terms" className="transition-colors hover:text-ink">
            Terms
          </Link>
        </div>
      </div>
    </div>
  );
}
