"use client";

/**
 * Site footer. Exists for one reason: the legal documents need a reachable,
 * permanent home — App Store review needs a URL it can open, and a person
 * deciding whether to scan their bedroom deserves to find the privacy policy
 * without hunting for it.
 *
 * It stands down on /room for the same reason SiteNav does: the room page is
 * immersive and carries its own floating chrome (design §5 — the room is the
 * page). The documents stay reachable from the account menu there.
 */

import Link from "next/link";
import { usePathname } from "next/navigation";

export default function SiteFooter() {
  const pathname = usePathname();
  if (pathname === "/room") return null;

  return (
    <footer className="mt-20 border-t border-ink/10">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 px-6 py-6 text-[13px]">
        <p className="font-mono text-[11px] text-ink/35">
          Rooms you scan stay yours.
        </p>
        <nav className="flex gap-5 text-ink/50">
          <Link href="/privacy" className="transition-colors hover:text-ink">
            Privacy
          </Link>
          <Link href="/terms" className="transition-colors hover:text-ink">
            Terms
          </Link>
        </nav>
      </div>
    </footer>
  );
}
