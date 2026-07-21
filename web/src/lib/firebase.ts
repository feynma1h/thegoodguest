/**
 * Firebase web auth (live mode only; loaded via dynamic import from
 * lib/api/index.ts so mock/live-local bundles never pull the SDK).
 *
 * Decision 0051: identity is the iOS capture app's Firebase user, upgraded
 * THERE from anonymous to a linked Sign in with Apple credential (linking
 * preserves the UID). The browser signs in with the same Apple ID and reads
 * that UID's scenes. The web is a READER of identity, never a creator:
 *
 *   - No anonymous sign-in here anymore. A browser-minted anonymous UID owns
 *     nothing and can never own anything (capture is iOS-only); it existed
 *     solely as the pre-0051 dev identity.
 *   - signInWithApple() refuses to create a Firebase user. If the sign-in
 *     comes back isNewUser, the fresh user is deleted on the spot and
 *     AppleIdNotLinkedError is thrown. An empty web-born account would
 *     permanently claim the Apple ID, and the LATER iOS link attempt — from
 *     the phone whose UID owns the actual rooms — would then hit a conflict
 *     with an account that owns nothing. Identity roots on the phone.
 *
 * Config comes from NEXT_PUBLIC_FIREBASE_* (see .env.example). The appId
 * currently registered is the roomstudio-smoke-test web app; a proper web
 * app registration is a launch task.
 */

import { getApps, initializeApp, type FirebaseApp } from "firebase/app";
import {
  getAdditionalUserInfo,
  getAuth,
  OAuthProvider,
  signInWithPopup,
  signOut,
  type Auth,
  type User,
} from "firebase/auth";

/** The Apple ID has no roomstudio account yet — sign in on iOS first.
 * `message` is display-ready product copy. */
export class AppleIdNotLinkedError extends Error {
  constructor() {
    super(
      "That Apple ID isn’t holding any rooms yet. Open the capture app on " +
        "your iPhone and sign in there first — your rooms follow it here.",
    );
    this.name = "AppleIdNotLinkedError";
  }
}

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

/**
 * The persisted user, or null when signed out. Waits for the SDK's initial
 * auth-state restoration — currentUser is always null for the first ticks
 * of a page load, and deciding "signed out" before restoration completes
 * would flash the sign-in panel at every signed-in visitor.
 */
export async function getCurrentUser(): Promise<User | null> {
  const a = getFirebaseAuth();
  await a.authStateReady();
  return a.currentUser;
}

/** Bearer token for LiveApiClient, or null when signed out (the client
 * turns null into its typed no_local_token error — the pages' signed-out
 * signal). Never triggers an interactive sign-in. */
export async function getFirebaseIdToken(): Promise<string | null> {
  try {
    const user = await getCurrentUser();
    return user ? await user.getIdToken() : null;
  } catch {
    return null;
  }
}

/**
 * Sign in with the Apple ID that was linked on iOS. Throws
 * AppleIdNotLinkedError — after deleting the just-created user — when this
 * Apple ID has no account yet (see module docstring for why the web must
 * never keep one). Popup-flow errors (closed popup etc.) propagate to the
 * caller untouched.
 */
export async function signInWithApple(): Promise<User> {
  const a = getFirebaseAuth();
  const provider = new OAuthProvider("apple.com");
  provider.addScope("email");
  const credential = await signInWithPopup(a, provider);
  if (getAdditionalUserInfo(credential)?.isNewUser) {
    try {
      await credential.user.delete();
    } catch {
      // Deletion needs a recent sign-in (we have one), so this is near
      // impossible — but never stay signed in to an account we refuse to
      // create. Sign-out still prevents the session; the stray empty user
      // is the lesser evil and the retry copy points at iOS anyway.
      await signOut(a);
    }
    throw new AppleIdNotLinkedError();
  }
  return credential.user;
}

/** Sign out — a real account operation since decision 0051 landed; the
 * account itself lives on, reachable from any device with the Apple ID. */
export async function signOutUser(): Promise<void> {
  await signOut(getFirebaseAuth());
}
