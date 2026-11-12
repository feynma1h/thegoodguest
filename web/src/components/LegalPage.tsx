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
 * Design (decision 0361): a reading page. The display face for the title and
 * the section heads, the summary as the document's italic lede, the body in
 * the interface face at a long-form measure, and the sections listed down
 * the side so a long policy can be walked rather than scrolled. Mono stays
 * for the machine-checkable facts (bucket names, retention windows,
 * endpoints). The site footer carries the links between documents.
 */

import { Children, isValidElement, type ReactNode } from "react";

import LegalToc from "@/components/LegalToc";

/** One numbered section. The number is its anchor (#s3), and the side
 * list reads its title from here, so the two can never disagree. */
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
    <section id={`s${n}`} aria-labelledby={`s${n}-h`} className="scroll-mt-28">
      <h2
        id={`s${n}-h`}
        className="mb-4 mt-14 font-serif text-[30px] font-normal leading-[1.15] tracking-[-0.015em] text-ink"
      >
        {title}
      </h2>
      <div className="space-y-4 text-[17px] leading-[1.7] text-[#2b3542] [&_strong]:text-ink [&_ul]:space-y-2 [&_ul]:pl-5 [&_ul]:marker:text-ink-3">
        {children}
      </div>
    </section>
  );
}

/** Machine data inline — bucket names, windows, endpoints. */
export function M({ children }: { children: ReactNode }) {
  return <code className="font-mono text-[0.87em] text-ink">{children}</code>;
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
  // The side list, read from the sections themselves.
  const sections = Children.toArray(children)
    .filter(
      (child): child is React.ReactElement<{ n: string; title: string }> =>
        isValidElement(child) && child.type === Section,
    )
    .map((child) => ({ id: `s${child.props.n}`, title: child.props.title }));

  return (
    <div className="mx-auto max-w-[1280px] px-6 pb-28 pt-12 sm:px-10 sm:pt-16">
      <h1 className="font-serif text-[clamp(48px,6vw,72px)] font-light leading-none tracking-[-0.03em] text-ink">
        {title}
      </h1>
      <p className="mt-[18px] text-[15px] text-ink-2">Last updated {updated}</p>

      <div className="mt-12 grid items-start gap-20 lg:mt-14 lg:grid-cols-[240px_minmax(0,1fr)]">
        <LegalToc sections={sections} />
        <article className="max-w-[680px]">
          <p className="font-serif text-[clamp(20px,1.9vw,23px)] italic leading-[1.5] text-ink">
            {summary}
          </p>
          {children}
        </article>
      </div>
    </div>
  );
}
