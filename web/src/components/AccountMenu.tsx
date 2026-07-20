"use client";

/**
 * The account surface: who am I, what mode is this, how do I leave. Until
 * decision 0051's linked sign-in ships, identity is thin (anonymous UID in
 * live mode, a named workspace in mock/local) — but the affordance exists
 * NOW so signing in/out has a home the day real accounts land, and so the
 * dev-only Viewer workbench has a dignified place off the primary nav.
 *
 * UID renders in mono (machine data, decision 0056). Sign out is live-mode
 * only; mock/local show what the identity actually is instead of a dead
 * button — honest about the current state, per the no-fake-UI rule.
 */

import { AnimatePresence, motion } from "motion/react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { SPRING } from "@/components/ui/spring";
import { apiMode } from "@/lib/api";

export default function AccountMenu() {
  const mode = apiMode();
  const [open, setOpen] = useState(false);
  const [uid, setUid] = useState<string | null>(null);
  const rootRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (mode !== "live") return;
    let cancelled = false;
    // Deferred import keeps the Firebase SDK out of mock/local bundles.
    import("@/lib/firebase").then(({ getCurrentUser }) =>
      getCurrentUser().then((user) => {
        if (!cancelled) setUid(user?.uid ?? null);
      }),
    );
    return () => {
      cancelled = true;
    };
  }, [mode]);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("pointerdown", onDown);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("pointerdown", onDown);
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const identity =
    mode === "mock"
      ? { title: "Demo workspace", detail: "Sample rooms, no account" }
      : mode === "live-local"
        ? { title: "Local dev", detail: "test-uid:dev-user" }
        : uid
          ? { title: "Signed in", detail: uid }
          : { title: "Signing in…", detail: null };

  const onSignOut = async () => {
    const { signOutUser } = await import("@/lib/firebase");
    await signOutUser();
    // Anonymous auth re-mints a UID on next load; a full reload keeps every
    // client (API, viewer) consistent with the fresh identity.
    window.location.href = "/";
  };

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-label="Account"
        aria-expanded={open}
        className="flex h-8 w-8 cursor-pointer items-center justify-center rounded-full border border-white/[0.12] text-zinc-400 transition-colors hover:border-white/25 hover:text-zinc-200"
      >
        <svg width="15" height="15" viewBox="0 0 15 15" fill="none" aria-hidden>
          <circle cx="7.5" cy="5.2" r="2.4" stroke="currentColor" strokeWidth="1.2" />
          <path
            d="M2.8 12.6c.9-2 2.6-3.1 4.7-3.1s3.8 1.1 4.7 3.1"
            stroke="currentColor"
            strokeWidth="1.2"
            strokeLinecap="round"
          />
        </svg>
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: 6, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 4, scale: 0.98 }}
            transition={SPRING}
            className="absolute right-0 top-11 z-40 w-64 overflow-hidden rounded-2xl border border-white/[0.08] bg-[#111] shadow-xl shadow-black/50"
          >
            <div className="border-b border-white/[0.06] px-4 py-3.5">
              <p className="text-sm font-medium text-zinc-200">{identity.title}</p>
              {identity.detail && (
                <p className="mt-1 truncate font-mono text-[10px] text-zinc-500">
                  {identity.detail}
                </p>
              )}
            </div>

            {mode !== "live" && (
              <div className="border-b border-white/[0.06] px-4 py-3">
                <p className="text-xs leading-relaxed text-zinc-500">
                  Sign-in arrives with accounts — rooms currently come from{" "}
                  {mode === "mock" ? "built-in demo data" : "your local backend"}.
                </p>
              </div>
            )}

            {mode !== "live" && (
              <Link
                href="/viewer"
                onClick={() => setOpen(false)}
                className="block px-4 py-3 text-sm text-zinc-400 transition-colors hover:bg-white/[0.04] hover:text-zinc-200"
              >
                Dev viewer
                <span className="ml-2 font-mono text-[10px] text-zinc-600">workbench</span>
              </Link>
            )}

            {mode === "live" && (
              <button
                type="button"
                onClick={onSignOut}
                className="block w-full cursor-pointer px-4 py-3 text-left text-sm text-zinc-400 transition-colors hover:bg-white/[0.04] hover:text-zinc-200"
              >
                Sign out
              </button>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
