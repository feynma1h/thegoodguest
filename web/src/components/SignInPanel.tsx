"use client";

/**
 * The way into the web app (decisions 0051, 0094). Two providers, one guard:
 * Apple first — it is the credential iOS links, and the only one whose
 * "not linked yet" branch resolves by signing in on the iPhone — then
 * Google, which exists so the web auth path is testable before Apple
 * Developer Program enrollment lands.
 *
 * Three outcomes need words: success reloads the page under the new
 * identity, IdentityNotLinkedError shows its own provider-specific copy, a
 * closed popup shows nothing. Errors render once, below both buttons, so a
 * retry with the other provider replaces the message rather than stacking.
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

type Provider = "apple" | "google";

function AppleMark() {
  return (
    <svg width="15" height="18" viewBox="0 0 15 18" fill="currentColor" aria-hidden>
      <path d="M12.52 9.56c.02 2.6 2.28 3.47 2.3 3.48-.02.06-.36 1.24-1.19 2.45-.71 1.05-1.46 2.1-2.63 2.12-1.15.02-1.52-.68-2.84-.68-1.31 0-1.72.66-2.81.7-1.13.05-1.99-1.13-2.71-2.18C1.17 13.32.05 9.4 1.56 6.75a4.2 4.2 0 0 1 3.56-2.16c1.11-.02 2.16.75 2.84.75.68 0 1.95-.92 3.29-.79.56.03 2.14.23 3.15 1.71-.08.05-1.88 1.1-1.88 3.3M10.35 3.15c.6-.73 1-1.74.9-2.75-.87.04-1.91.58-2.53 1.3-.56.64-1.05 1.67-.91 2.65.96.08 1.94-.49 2.54-1.2" />
    </svg>
  );
}

function GoogleMark() {
  // Google's four-colour G, per their branding guidelines — the one place
  // in this app where fixed brand colours override the palette.
  return (
    <svg width="16" height="16" viewBox="0 0 18 18" aria-hidden>
      <path fill="#4285F4" d="M17.64 9.2c0-.64-.06-1.25-.16-1.84H9v3.48h4.84a4.14 4.14 0 0 1-1.8 2.72v2.26h2.92c1.7-1.57 2.68-3.88 2.68-6.62" />
      <path fill="#34A853" d="M9 18c2.43 0 4.47-.8 5.96-2.18l-2.92-2.26c-.8.54-1.84.86-3.04.86-2.34 0-4.32-1.58-5.03-3.7H.96v2.33A9 9 0 0 0 9 18" />
      <path fill="#FBBC05" d="M3.97 10.72a5.4 5.4 0 0 1 0-3.44V4.95H.96a9 9 0 0 0 0 8.1z" />
      <path fill="#EA4335" d="M9 3.58c1.32 0 2.5.45 3.44 1.35l2.58-2.58C13.46.9 11.43 0 9 0A9 9 0 0 0 .96 4.95l3.01 2.33C4.68 5.16 6.66 3.58 9 3.58" />
    </svg>
  );
}

const LABEL: Record<Provider, string> = {
  apple: "Sign in with Apple",
  google: "Sign in with Google",
};

export default function SignInPanel({
  compact = false,
}: {
  /** Smaller paddings for tight homes (menus, side panels). */
  compact?: boolean;
}) {
  const [busy, setBusy] = useState<Provider | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void import("@/lib/firebase");
  }, []);

  const onClick = async (provider: Provider) => {
    if (busy) return;
    setBusy(provider);
    setError(null);
    const { signInWithApple, signInWithGoogle, IdentityNotLinkedError } =
      await import("@/lib/firebase");
    try {
      await (provider === "apple" ? signInWithApple() : signInWithGoogle());
      // Every client (API, viewer, menus) refetches under the new identity.
      window.location.reload();
    } catch (exc: unknown) {
      if (exc instanceof IdentityNotLinkedError) {
        setError(exc.message);
      } else if (!QUIET_CODES.has((exc as { code?: string }).code ?? "")) {
        setError(GENERIC_ERROR);
      }
      setBusy(null);
    }
  };

  const shared = `flex cursor-pointer items-center justify-center gap-2.5 rounded-full font-medium transition-opacity hover:opacity-85 disabled:cursor-default disabled:opacity-60 ${
    compact ? "px-4 py-2.5 text-[13px]" : "px-7 py-3 text-sm"
  }`;

  return (
    <div className="flex flex-col items-center">
      {/* items-stretch inside a shrink-to-fit column: both buttons take the
          width of the wider label, so they read as one control. */}
      <div className={`flex flex-col items-stretch ${compact ? "w-full" : ""}`}>
        <button
          type="button"
          onClick={() => onClick("apple")}
          disabled={busy !== null}
          className={`${shared} bg-black text-white`}
        >
          <AppleMark />
          {busy === "apple" ? "Signing in…" : LABEL.apple}
        </button>

        <button
          type="button"
          onClick={() => onClick("google")}
          disabled={busy !== null}
          className={`${shared} mt-2.5 border border-ink/15 bg-paper text-ink`}
        >
          <GoogleMark />
          {busy === "google" ? "Signing in…" : LABEL.google}
        </button>
      </div>

      {error && (
        <p
          className={`mt-3 text-xs leading-relaxed text-accent-deep ${
            compact ? "text-left" : "max-w-sm text-center"
          }`}
        >
          {error}
        </p>
      )}
    </div>
  );
}
