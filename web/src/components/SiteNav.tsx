"use client";

/**
 * Top navigation. Deliberately three things and no more: where your rooms
 * are, how a new one starts, and who you are. The dev Viewer workbench
 * lives inside the account menu (non-live modes), not the primary nav —
 * top-level tabs are for the product, not its tooling. "New room" opens
 * the sheet in place instead of navigating away.
 */

import Link from "next/link";
import { usePathname } from "next/navigation";

import AccountMenu from "@/components/AccountMenu";
import NewRoomSheet, { openNewRoomSheet } from "@/components/NewRoomSheet";
import Wordmark from "@/components/Wordmark";
import { PillButton } from "@/components/ui/spring";

export default function SiteNav() {
  const pathname = usePathname();
  const inRooms = pathname === "/rooms" || pathname === "/room";

  return (
    <header className="sticky top-0 z-20 border-b border-white/[0.06] bg-background/70 backdrop-blur-xl">
      <nav className="mx-auto flex h-14 max-w-6xl items-center justify-between px-6">
        <Link href="/" className="transition-opacity hover:opacity-70">
          <Wordmark />
        </Link>
        <div className="flex items-center gap-5 text-sm">
          <Link
            href="/rooms"
            className={`transition-colors hover:text-foreground ${
              inRooms ? "text-foreground" : "text-zinc-400"
            }`}
          >
            Rooms
          </Link>
          <PillButton onClick={openNewRoomSheet} className="!px-4 !py-1.5">
            New room
          </PillButton>
          <AccountMenu />
        </div>
      </nav>
      <NewRoomSheet />
    </header>
  );
}
