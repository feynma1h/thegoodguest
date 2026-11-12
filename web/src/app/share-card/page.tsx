"use client";

/**
 * The share image: web/public/og-card.png, the 1200×630 picture a link to
 * the site unfurls into (decision 0361). The site draws it itself, with the
 * landing's own sample room, wordmark and faces, so the picture people see
 * before they arrive is the site they arrive at. It replaced the hand-drawn
 * docs/product/og-card.html, which stays as the precedent the card
 * geometry tests reproduce.
 *
 * What it may say: the landing's own claim, and the true hosting URL
 * (lib/card/layout's DOMAIN — not the product name). The room is the sample,
 * never a person's, and its sizes print to one decimal like every other
 * measurement the product shows.
 *
 * Inert unless NEXT_PUBLIC_SHARE_CARD=1, like /shell-finish: a production
 * build leaves it unset, and the page is then the ordinary not-found page.
 *
 * Re-export (exactly 1200×630), then rebuild without the flag:
 *
 *   NEXT_PUBLIC_SHARE_CARD=1 npm --prefix web run build
 *   npx --yes serve web/out -l 3210        # clean URLs, as hosting serves them
 *   "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
 *     --headless=new --hide-scrollbars --enable-unsafe-swiftshader \
 *     --window-size=1200,630 --force-device-scale-factor=1 \
 *     --virtual-time-budget=15000 \
 *     --screenshot=web/public/og-card.png http://localhost:3210/share-card
 *
 * Re-export triggers: a copy change on the landing, the identity changing,
 * or the sample room changing.
 */

import NotFoundScreen from "@/components/NotFound";
import SampleRoom from "@/components/SampleRoom";
import { Wordmark } from "@/components/Wordmark";
import { DOMAIN } from "@/lib/card/layout";

export default function ShareCard() {
  if (process.env.NEXT_PUBLIC_SHARE_CARD !== "1") return <NotFoundScreen />;

  // Fixed over the site's own chrome, so a 1200×630 window holds the card
  // and nothing else.
  return (
    <div className="fixed left-0 top-0 z-[100] grid h-[630px] w-[1200px] grid-cols-[560px_1fr] overflow-hidden bg-paper text-ink">
      <div className="flex flex-col pb-14 pl-16 pt-[60px]">
        {/* self-start: a stretched SVG would centre the name in the column. */}
        <div className="self-start">
          <Wordmark height="56px" />
        </div>
        <h1 className="mt-16 font-serif text-[78px] font-light leading-[0.98] tracking-[-0.035em]">
          Meet your room again.
        </h1>
        <p className="mt-[26px] max-w-[25ch] text-[23px] leading-[1.45] text-ink-2">
          Walk a room with your iPhone. It stands back up in 3D, at its true size.
        </p>
        <p className="mt-auto font-mono text-[18px] text-ink-2">{DOMAIN}</p>
      </div>
      <div className="relative my-10 mr-10 overflow-hidden rounded-[28px] bg-parchment">
        <SampleRoom
          label="A sample room rebuilt in 3D, cut away so you can see in, with its measured size"
          view={0}
          labels
          fit={0.92}
          interactive={false}
          className="absolute inset-0"
        />
      </div>
    </div>
  );
}
