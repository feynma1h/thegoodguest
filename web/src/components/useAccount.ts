"use client";

/**
 * Who is here, for the chrome that has to know (decision 0361): the nav
 * swaps "Your house" and the account button for "Sign in" when nobody is,
 * the account menu names how you signed in, and the phone-to-desk page says
 * which account it is listening for.
 *
 * Only live mode has a real identity. Mock and live-local always have their
 * fixed demo one, so they never show a sign-in. In live mode the answer
 * waits for Firebase to restore its persisted session (getCurrentUser), so a
 * signed-in visitor never sees a flash of "Sign in".
 */

import { useEffect, useState } from "react";

import { apiMode } from "@/lib/api";

export type Provider = "apple" | "google";

export type Account =
  | { phase: "demo"; mode: "mock" | "live-local" }
  | { phase: "checking" }
  | { phase: "signedOut" }
  | {
      phase: "signedIn";
      uid: string;
      email: string | null;
      /** The provider the person signed in with, when the session says. */
      provider: Provider | null;
    };

/** "Signed in with Apple": what the account menu and the desk say. */
export function signedInWith(account: Account): string | null {
  if (account.phase !== "signedIn") return null;
  if (account.provider === "apple") return "Signed in with Apple";
  if (account.provider === "google") return "Signed in with Google";
  return "Signed in";
}

export function useAccount(): Account {
  const mode = apiMode();
  const [live, setLive] = useState<Account>({ phase: "checking" });

  useEffect(() => {
    if (mode !== "live") return;
    let cancelled = false;
    // Deferred import keeps the Firebase SDK out of mock/live-local bundles.
    import("@/lib/firebase")
      .then(({ getCurrentUser }) => getCurrentUser())
      .then((user) => {
        if (cancelled) return;
        if (!user) {
          setLive({ phase: "signedOut" });
          return;
        }
        const ids = user.providerData.map((p) => p.providerId);
        setLive({
          phase: "signedIn",
          uid: user.uid,
          email: user.email,
          provider: ids.includes("apple.com")
            ? "apple"
            : ids.includes("google.com")
              ? "google"
              : null,
        });
      })
      .catch(() => {
        if (!cancelled) setLive({ phase: "signedOut" });
      });
    return () => {
      cancelled = true;
    };
  }, [mode]);

  return mode === "live" ? live : { phase: "demo", mode };
}
