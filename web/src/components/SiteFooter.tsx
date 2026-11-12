"use client";

/**
 * Site footer, in the dusk register the landing ends on (decision 0361). It
 * exists first for one reason: the legal documents need a reachable,
 * permanent home — App Store review needs a URL it can open, and a person
 * deciding whether to scan their bedroom deserves to find the privacy policy
 * without hunting for it.
 *
 * It carries the wordmark in its reversed ink, at the script's legible floor
 * (see Wordmark.tsx), and never the mark beside it.
 *
 * It stands down on /room for the same reason SiteNav does: the room page is
 * immersive and carries its own floating chrome.
 */

import Link from "next/link";
import { usePathname } from "next/navigation";

import { Wordmark } from "@/components/Wordmark";

const LINKS = [
  { href: "/rooms", label: "Your house" },
  { href: "/new", label: "Scan a room" },
  { href: "/privacy", label: "Privacy" },
  { href: "/terms", label: "Terms" },
] as const;

export default function SiteFooter() {
  const pathname = usePathname();
  if (pathname === "/room") return null;

  return (
    <footer className="bg-dusk text-on-dusk">
      <div className="mx-auto max-w-[1280px] px-6 pb-10 pt-14 sm:px-10">
        <div className="flex flex-wrap items-center justify-between gap-8">
          <Wordmark height="50px" tone="reverse" />
          <nav aria-label="Footer" className="flex flex-wrap gap-x-8 gap-y-3 text-[15px] font-medium">
            {LINKS.map((l) => (
              <Link key={l.href} href={l.href} className="text-on-dusk-2 transition-colors hover:text-on-dusk">
                {l.label}
              </Link>
            ))}
            <a href="/third-party-notices.txt" className="text-on-dusk-2 transition-colors hover:text-on-dusk">
              Licences
            </a>
          </nav>
        </div>
        <div className="mt-11 flex flex-wrap justify-between gap-6 border-t border-on-dusk/10 pt-6 text-sm text-on-dusk-2">
          <p>Rooms you scan stay yours.</p>
          <p>© 2026 The Good Guest</p>
        </div>
      </div>
    </footer>
  );
}
