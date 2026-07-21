"use client";

/**
 * Sign in with Apple — the one way into the web app (decision 0051; Apple
 * only, because iOS ships Apple-only for App Store 4.8 symmetry). Wraps the
 * popup flow from lib/firebase with the three outcomes that need words:
 * success reloads the page under the new identity, AppleIdNotLinkedError
 * shows its own copy (sign in on the iPhone first), a closed popup shows
 * nothing. Black button per Apple's sign-in guidelines.
 *
 * The firebase module is preloaded on mount so the click handler's dynamic
 * import resolves from cache — Safari's transient-activation window for
 * popups doesn't survive a slow chunk fetch.
 */

import { useEffect, useState } from "react";

const GENERIC_ERROR = "Sign-in didn’t complete. Try again.";

/** Popup dismissals the user caused on purpose — never show an error. */
const QUIET_CODES = new Set([
  "auth/popup-closed-by-user",
  "auth/cancelled-popup-request",
  "auth/user-cancelled",
]);

export default function AppleSignInButton({
  compact = false,
}: {
  /** Smaller paddings for tight homes (menus, side panels). */
  compact?: boolean;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void import("@/lib/firebase");
  }, []);

  const onClick = async () => {
    if (busy) return;
    setBusy(true);
    setError(null);
    const { signInWithApple, AppleIdNotLinkedError } = await import(
      "@/lib/firebase"
    );
    try {
      await signInWithApple();
      // Every client (API, viewer, menus) refetches under the new identity.
      window.location.reload();
    } catch (exc: unknown) {
      if (exc instanceof AppleIdNotLinkedError) {
        setError(exc.message);
      } else if (
        !QUIET_CODES.has((exc as { code?: string }).code ?? "")
      ) {
        setError(GENERIC_ERROR);
      }
      setBusy(false);
    }
  };

  return (
    <div className={compact ? "" : "flex flex-col items-center"}>
      <button
        type="button"
        onClick={onClick}
        disabled={busy}
        className={`flex cursor-pointer items-center justify-center gap-2.5 rounded-full bg-black font-medium text-white transition-opacity hover:opacity-85 disabled:cursor-default disabled:opacity-60 ${
          compact ? "w-full px-4 py-2.5 text-[13px]" : "px-7 py-3 text-sm"
        }`}
      >
        <svg
          width="15"
          height="18"
          viewBox="0 0 15 18"
          fill="currentColor"
          aria-hidden
        >
          <path d="M12.52 9.56c.02 2.6 2.28 3.47 2.3 3.48-.02.06-.36 1.24-1.19 2.45-.71 1.05-1.46 2.1-2.63 2.12-1.15.02-1.52-.68-2.84-.68-1.31 0-1.72.66-2.81.7-1.13.05-1.99-1.13-2.71-2.18C1.17 13.32.05 9.4 1.56 6.75a4.2 4.2 0 0 1 3.56-2.16c1.11-.02 2.16.75 2.84.75.68 0 1.95-.92 3.29-.79.56.03 2.14.23 3.15 1.71-.08.05-1.88 1.1-1.88 3.3M10.35 3.15c.6-.73 1-1.74.9-2.75-.87.04-1.91.58-2.53 1.3-.56.64-1.05 1.67-.91 2.65.96.08 1.94-.49 2.54-1.2" />
        </svg>
        {busy ? "Signing in…" : "Sign in with Apple"}
      </button>
      {error && (
        <p
          className={`mt-3 text-xs leading-relaxed text-accent ${
            compact ? "" : "max-w-sm text-center"
          }`}
        >
          {error}
        </p>
      )}
    </div>
  );
}
