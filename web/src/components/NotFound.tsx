/**
 * Page not found (decision 0361). Any address the site doesn't have lands
 * here: the static export writes it as 404.html, and hosting serves that for
 * every unmatched path. It sits inside the site's own nav and footer, says
 * plainly what happened, and offers the two places worth going.
 *
 * The drawing is a plan symbol: a room's outline in the dashed line the site
 * uses for what isn't there, with a door left open.
 */

import { PillLink } from "@/components/ui/spring";

export default function NotFoundScreen() {
  return (
    <div className="flex min-h-[calc(100dvh-76px-240px)] items-center justify-center px-6 py-20 sm:px-10">
      <div className="w-full max-w-[620px]">
        <svg width="132" height="96" viewBox="0 0 132 96" aria-hidden className="mb-[34px] block">
          <path d="M4 4 H128 V92 H78" fill="none" stroke="#808b98" strokeWidth="2" strokeDasharray="9 8" />
          <path d="M44 92 H4 V4" fill="none" stroke="#808b98" strokeWidth="2" strokeDasharray="9 8" />
          <path d="M44 92 A34 34 0 0 1 78 58" fill="none" stroke="#c04d3e" strokeWidth="1.4" />
          <path d="M44 92 V58" fill="none" stroke="#c04d3e" strokeWidth="1.4" />
        </svg>
        <h1 className="font-serif text-[clamp(40px,4.6vw,56px)] font-light leading-[1.04] tracking-[-0.03em] text-ink">
          There&rsquo;s no room at this address.
        </h1>
        <p className="mt-[22px] max-w-[34rem] text-[17px] leading-[1.55] text-ink-2">
          The link may be old, or the page may have moved. Your rooms are where
          you left them.
        </p>
        <div className="mt-[34px] flex flex-wrap gap-3">
          <PillLink href="/rooms" size="lg">
            Your house
          </PillLink>
          <PillLink href="/" variant="ghost" size="lg">
            Home
          </PillLink>
        </div>
      </div>
    </div>
  );
}
