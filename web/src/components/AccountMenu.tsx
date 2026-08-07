"use client";

/**
 * The account surface: who am I, what mode is this, how do I leave. In live
 * mode this is decision 0051's web half: sign in with the Apple ID that was
 * linked on the iPhone (the web never creates accounts — see lib/firebase),
 * see who you are, sign out. Mock/local show what the identity actually is
 * instead of a dead button — honest about the current state, per the
 * no-fake-UI rule.
 *
 * UID renders in mono (machine data, decision 0056).
 */

import { AnimatePresence, motion } from "motion/react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import SignInPanel from "@/components/SignInPanel";
import { SPRING } from "@/components/ui/spring";
import { apiMode } from "@/lib/api";

type LiveAuth =
  | { phase: "checking" }
  | { phase: "signedOut" }
  | { phase: "signedIn"; uid: string; email: string | null };

export default function AccountMenu() {
  const mode = apiMode();
  const [open, setOpen] = useState(false);
  const [liveAuth, setLiveAuth] = useState<LiveAuth>({ phase: "checking" });
  const rootRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (mode !== "live") return;
    let cancelled = false;
    // Deferred import keeps the Firebase SDK out of mock/local bundles.
    import("@/lib/firebase").then(({ getCurrentUser }) =>
      getCurrentUser().then((user) => {
        if (cancelled) return;
        setLiveAuth(
          user
            ? { phase: "signedIn", uid: user.uid, email: user.email }
            : { phase: "signedOut" },
        );
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
        : liveAuth.phase === "signedIn"
          ? { title: "Signed in", detail: liveAuth.email ?? liveAuth.uid }
          : liveAuth.phase === "signedOut"
            ? { title: "Not signed in", detail: null }
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
        onClick={() => setOpen((v) => !v)}
        aria-label="Account"
        aria-expanded={open}
        className="flex h-8 w-8 cursor-pointer items-center justify-center rounded-full border border-ink/25 text-ink/60 transition-colors hover:border-ink/50 hover:text-ink"
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
            className="absolute right-0 top-11 z-40 w-64 overflow-hidden rounded-2xl border border-ink/15 bg-white shadow-float"
          >
            <div className="border-b border-ink/10 px-4 py-3.5">
              <p className="text-sm font-medium text-ink">{identity.title}</p>
              {identity.detail && (
                <p className="mt-1 truncate font-mono text-[10px] text-ink/45">
                  {identity.detail}
                </p>
              )}
            </div>

            {mode !== "live" && (
              <div className="border-b border-ink/10 px-4 py-3">
                <p className="text-xs leading-relaxed text-ink/55">
                  Sign-in arrives with accounts — rooms currently come from{" "}
                  {mode === "mock" ? "built-in demo data" : "your local backend"}.
                </p>
              </div>
            )}

            {mode !== "live" && (
              <Link
                href="/viewer"
                onClick={() => setOpen(false)}
                className="block px-4 py-3 text-sm text-ink/70 transition-colors hover:bg-ink/[0.04] hover:text-ink"
              >
                Dev viewer
                <span className="ml-2 font-mono text-[10px] text-ink/40">workbench</span>
              </Link>
            )}

            {mode === "live" && liveAuth.phase === "signedOut" && (
              <div className="px-4 py-4">
                <p className="mb-3 text-xs leading-relaxed text-ink/55">
                  Sign in with the account from your iPhone — the rooms you
                  scanned there follow it here.
                </p>
                <SignInPanel compact />
              </div>
            )}

            {mode === "live" && liveAuth.phase === "signedIn" && (
              <button
                type="button"
                onClick={onSignOut}
                className="block w-full cursor-pointer px-4 py-3 text-left text-sm text-ink/70 transition-colors hover:bg-ink/[0.04] hover:text-ink"
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
