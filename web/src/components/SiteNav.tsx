"use client";

/**
 * Top navigation. The wordmark, where your house is, how a new room starts,
 * and who you are; on the landing, three anchors into the page as well. The
 * dev Viewer workbench lives inside the account menu (non-live modes), not
 * here — top-level links are for the product, not its tooling. "Scan a room"
 * opens the sheet in place instead of navigating away.
 *
 * The header carries the WORDMARK, not the mark (decision 0361): this is the
 * page a stranger meets first, and a small abstract mark tells a stranger
 * nothing (0248's own reason for giving the card the name). It is set at the
 * script's legible floor — see Wordmark.tsx — and never beside the mark.
 *
 * On /room the nav disappears entirely: the room page is immersive and
 * carries its own floating chrome.
 */

import Link from "next/link";
import { usePathname } from "next/navigation";

import AccountMenu from "@/components/AccountMenu";
import NewRoomSheet, { openNewRoomSheet } from "@/components/NewRoomSheet";
import { usePitchShowing } from "@/components/pitchPresence";
import { useAccount } from "@/components/useAccount";
import { Wordmark } from "@/components/Wordmark";
import { PillButton } from "@/components/ui/spring";

const LANDING_ANCHORS = [
  { href: "#how", label: "How it works" },
  { href: "#guest", label: "The guest" },
  { href: "#privacy", label: "Privacy" },
] as const;

export default function SiteNav() {
  const pathname = usePathname();
  const account = useAccount();
  const pitchShowing = usePitchShowing();
  if (pathname === "/room") return null;
  const inHouse = pathname === "/rooms";
  // The section links point into the pitch, so a returning visitor's
  // greeting on "/" goes without them.
  const onLanding = pathname === "/" && pitchShowing;

  return (
    <header className="sticky top-0 z-20 bg-paper/85 backdrop-blur-xl backdrop-saturate-150">
      <nav
        aria-label="Main"
        className="mx-auto flex h-[76px] max-w-[1392px] items-center justify-between gap-6 px-6 sm:px-10"
      >
        <Link href="/" aria-label="The Good Guest, home" className="transition-opacity hover:opacity-80">
          <Wordmark height="50px" />
        </Link>
        {onLanding && (
          <div className="hidden items-center gap-9 md:flex">
            {LANDING_ANCHORS.map((a) => (
              <a
                key={a.href}
                href={a.href}
                className="text-[15px] font-medium text-ink-2 transition-colors hover:text-ink"
              >
                {a.label}
              </a>
            ))}
          </div>
        )}
        <div className="flex items-center gap-5">
          {/* Nobody signed in: the house is where signing in happens, so
              the one link says so. Nothing shows while Firebase restores a
              session — a signed-in visitor must never see "Sign in" flash. */}
          {account.phase !== "checking" && (
            <Link
              href="/rooms"
              aria-current={inHouse ? "page" : undefined}
              className={`text-[15px] font-medium transition-colors hover:text-ink ${
                account.phase === "signedOut" ? "block" : "hidden sm:block"
              } ${inHouse ? "text-ink" : "text-ink-2"}`}
            >
              {account.phase === "signedOut" ? "Sign in" : "Your house"}
            </Link>
          )}
          {/* A phone has room for the wordmark at its legible floor and one
              control beside it, so the scan pill steps back there; every
              page and the footer still offer it. */}
          <PillButton
            onClick={openNewRoomSheet}
            className="!h-10 !px-[18px] !py-0 !text-[14.5px] max-sm:!hidden"
          >
            Scan a room
          </PillButton>
          {(account.phase === "signedIn" || account.phase === "demo") && (
            <AccountMenu account={account} />
          )}
        </div>
      </nav>
      <NewRoomSheet />
    </header>
  );
}
