/**
 * Firebase web auth (live mode only; loaded via dynamic import from
 * lib/api/index.ts so mock/live-local bundles never pull the SDK).
 *
 * Signs in anonymously against the same Firebase project as the iOS app.
 * DEV-ONLY IDENTITY: a browser anonymous UID is unrelated to any phone's
 * UID, so a live-mode session sees an empty scene list. Real cross-device
 * login is blocked on the iOS anonymous→linked-sign-in upgrade (decision
 * 0051); this module is the seam where that lands (swap signInAnonymously
 * for the real provider flow).
 *
 * Config comes from NEXT_PUBLIC_FIREBASE_* (see .env.example). The appId
 * currently registered is the roomstudio-smoke-test web app; a proper web
 * app registration is a launch task.
 */

import { getApps, initializeApp, type FirebaseApp } from "firebase/app";
import {
  getAuth,
  signInAnonymously,
  type Auth,
  type User,
} from "firebase/auth";

function requireEnv(name: string, value: string | undefined): string {
  if (!value) {
    throw new Error(`${name} is required for NEXT_PUBLIC_API_MODE=live`);
  }
  return value;
}

let auth: Auth | null = null;

function getFirebaseAuth(): Auth {
  if (auth === null) {
    const app: FirebaseApp =
      getApps()[0] ??
      initializeApp({
        apiKey: requireEnv(
          "NEXT_PUBLIC_FIREBASE_API_KEY",
          process.env.NEXT_PUBLIC_FIREBASE_API_KEY,
        ),
        authDomain:
          process.env.NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN ?? "roomstudio.firebaseapp.com",
        projectId: process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID ?? "roomstudio",
        appId: requireEnv(
          "NEXT_PUBLIC_FIREBASE_APP_ID",
          process.env.NEXT_PUBLIC_FIREBASE_APP_ID,
        ),
      });
    auth = getAuth(app);
  }
  return auth;
}

export async function ensureSignedIn(): Promise<User> {
  const a = getFirebaseAuth();
  if (a.currentUser) return a.currentUser;
  const cred = await signInAnonymously(a);
  return cred.user;
}

export async function getFirebaseIdToken(): Promise<string | null> {
  try {
    const user = await ensureSignedIn();
    return await user.getIdToken();
  } catch {
    return null;
  }
}

/** Current user for the account menu; resolves null when signed out. */
export async function getCurrentUser(): Promise<User | null> {
  try {
    return await ensureSignedIn();
  } catch {
    return null;
  }
}

/**
 * Sign out. NOTE: with today's anonymous auth this orphans the anon UID —
 * acceptable for the dev-only identity; once decision 0051's linked
 * sign-in lands, sign-out becomes a real account operation and this stays
 * the single call site.
 */
export async function signOutUser(): Promise<void> {
  const { signOut } = await import("firebase/auth");
  await signOut(getFirebaseAuth());
}
