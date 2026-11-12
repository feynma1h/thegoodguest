"use client";

/**
 * The account menu (decision 0361): who you are, the places the site has,
 * and how to leave. In live mode this is decision 0051's web half — the web
 * never creates accounts (see lib/firebase), so it names the account the
 * iPhone signed in with, signs out, and carries deletion, the one account
 * operation iOS cannot offer (0064: no sign-out there). Mock and live-local
 * say what the identity actually is instead of showing a dead button, and
 * keep the dev viewer one click away.
 *
 * A signed-out visitor never sees this: the nav offers "Sign in" instead.
 * The legal documents live here as well as in the footer, because the footer
 * stands down on /room — exactly where someone is looking at a scan of their
 * bedroom and may want to know what happens to it.
 */

import { AnimatePresence, motion } from "motion/react";
import Link from "next/link";
import { useCallback, useEffect, useId, useRef, useState } from "react";

import DeleteAccountDialog from "@/components/DeleteAccountPanel";
import { openNewRoomSheet } from "@/components/NewRoomSheet";
import { signedInWith, type Account } from "@/components/useAccount";
import { SPRING } from "@/components/ui/spring";

const ITEM =
  "flex h-11 w-full cursor-pointer items-center rounded-xl px-3.5 text-left text-[15px] font-medium text-ink transition-colors hover:bg-paper";

export default function AccountMenu({ account }: { account: Account }) {
  const [open, setOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const panelId = useId();

  const closeMenu = useCallback(() => setOpen(false), []);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) closeMenu();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") closeMenu();
    };
    window.addEventListener("pointerdown", onDown);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("pointerdown", onDown);
      window.removeEventListener("keydown", onKey);
    };
  }, [open, closeMenu]);

  const identity =
    account.phase === "demo"
      ? account.mode === "mock"
        ? { title: "Demo workspace", detail: "Sample rooms, no account." }
        : { title: "Local dev", detail: "Rooms from your local backend." }
      : account.phase === "signedIn"
        ? { title: signedInWith(account) ?? "Signed in", detail: "Your rooms follow this account." }
        : { title: "One moment…", detail: null };

  const onSignOut = async () => {
    const { signOutUser } = await import("@/lib/firebase");
    await signOutUser();
    // Full reload so every client (API, viewer, menus) drops the identity.
    window.location.href = "/";
  };

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-label="Your account"
        aria-expanded={open}
        aria-controls={panelId}
        className="grid h-10 w-10 cursor-pointer place-items-center rounded-full bg-parchment text-ink transition-colors hover:bg-[#d8dee4]"
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden>
          <circle cx="12" cy="8" r="4" />
          <path d="M4 21a8 8 0 0 1 16 0" />
        </svg>
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            id={panelId}
            initial={{ opacity: 0, y: 6, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 4, scale: 0.98 }}
            transition={SPRING}
            className="absolute right-0 top-12 z-40 w-[300px] origin-top-right rounded-3xl bg-white p-2.5 shadow-deep"
          >
            <div className="mb-1.5 border-b border-ink/[0.08] px-3.5 pb-4 pt-3.5">
              <p className="text-[15px] font-semibold text-ink">{identity.title}</p>
              {identity.detail && (
                <p className="mt-1 text-[13.5px] text-ink-2">{identity.detail}</p>
              )}
              {account.phase === "signedIn" && account.email && (
                <p className="mt-1 truncate text-[13.5px] text-ink-2">{account.email}</p>
              )}
            </div>

            <Link href="/rooms" onClick={closeMenu} className={ITEM}>
              Your house
            </Link>
            <button
              type="button"
              onClick={() => {
                closeMenu();
                openNewRoomSheet();
              }}
              className={ITEM}
            >
              Scan a room
            </button>
            <Link href="/privacy" onClick={closeMenu} className={ITEM}>
              Privacy
            </Link>
            <Link href="/terms" onClick={closeMenu} className={ITEM}>
              Terms
            </Link>

            <div className="mx-1 my-1.5 h-px bg-ink/[0.08]" />

            {account.phase === "demo" && (
              <Link href="/viewer" onClick={closeMenu} className={`${ITEM} justify-between`}>
                Dev viewer
                <span className="text-[13px] font-normal text-ink-2">Workbench</span>
              </Link>
            )}

            {account.phase === "signedIn" && (
              <>
                <button type="button" onClick={onSignOut} className={ITEM}>
                  Sign out
                </button>
                <button
                  type="button"
                  onClick={() => {
                    closeMenu();
                    setDeleting(true);
                  }}
                  className={`${ITEM} text-accent-deep`}
                >
                  Delete account
                </button>
              </>
            )}
          </motion.div>
        )}
      </AnimatePresence>

      {account.phase === "signedIn" && (
        <DeleteAccountDialog
          open={deleting}
          uid={account.uid}
          onClose={() => setDeleting(false)}
        />
      )}
    </div>
  );
}
