"use client";

/**
 * Top navigation. Deliberately three things and no more: where your house
 * is, how a new room starts, and who you are. The dev Viewer workbench
 * lives inside the account menu (non-live modes), not the primary nav —
 * top-level tabs are for the product, not its tooling. "Scan a room"
 * opens the sheet in place instead of navigating away.
 *
 * On /room the nav disappears entirely: the room page is immersive and
 * carries its own floating chrome (design §5 — the room is the page).
 */

import Link from "next/link";
import { usePathname } from "next/navigation";

import AccountMenu from "@/components/AccountMenu";
import NewRoomSheet, { openNewRoomSheet } from "@/components/NewRoomSheet";
import Wordmark from "@/components/Wordmark";
import { PillButton } from "@/components/ui/spring";

export default function SiteNav() {
  const pathname = usePathname();
  if (pathname === "/room") return null;
  const inHouse = pathname === "/rooms";

  return (
    <header className="sticky top-0 z-20 border-b border-ink/10 bg-paper/85 backdrop-blur-xl">
      <nav className="mx-auto flex h-14 max-w-6xl items-center justify-between px-6">
        <Link href="/" className="transition-opacity hover:opacity-70">
          <Wordmark />
        </Link>
        <div className="flex items-center gap-5 text-sm">
          <Link
            href="/rooms"
            className={`font-medium transition-colors hover:text-ink ${
              inHouse ? "text-ink" : "text-ink/55"
            }`}
          >
            Your house
          </Link>
          <PillButton onClick={openNewRoomSheet} className="!px-4 !py-1.5 !text-[13px]">
            Scan a room
          </PillButton>
          <AccountMenu />
        </div>
      </nav>
      <NewRoomSheet />
    </header>
  );
}
