/**
 * Firebase web auth (live mode only; loaded via dynamic import from
 * lib/api/index.ts so mock/live-local bundles never pull the SDK).
 *
 * Decision 0051: identity is the iOS capture app's Firebase user, upgraded
 * THERE from anonymous to a linked federated credential (linking preserves
 * the UID). The browser signs in with the same identity and reads that UID's
 * scenes. The web is a READER of identity, never a creator:
 *
 *   - No anonymous sign-in here anymore. A browser-minted anonymous UID owns
 *     nothing and can never own anything (capture is iOS-only); it existed
 *     solely as the pre-0051 dev identity.
 *   - Every sign-in here refuses to CREATE a Firebase user. If the popup
 *     comes back isNewUser, the fresh user is deleted on the spot and a
 *     typed IdentityNotLinkedError is thrown. An empty web-born account
 *     would permanently claim that identity, and the LATER iOS link attempt
 *     — from the phone whose UID owns the actual rooms — would then hit
 *     credential-already-in-use against an account that owns nothing.
 *     Identity roots on the phone.
 *
 * Decision 0094 adds Google alongside Apple. The never-create rule is
 * PROVIDER-AGNOSTIC — the failure it prevents is identical for Google — so
 * signInWithGoogle runs the same guard through the same code path. Apple
 * stays the primary: it is the credential iOS links, and the only one whose
 * refusal branch resolves by doing the iOS link. See 0094 for the recorded
 * asymmetry (iOS links Apple only today, so a Google sign-in succeeds only
 * for an account that already carries a google.com credential).
 *
 * Config comes from NEXT_PUBLIC_FIREBASE_* (see .env.example; the committed
 * .env.production carries the deploy build's values). The registered app is
 * roomstudio-web (2026-07-22) — the proper registration that replaced the
 * roomstudio-smoke-test appId.
 */

import { getApps, initializeApp, type FirebaseApp } from "firebase/app";
import {
  getAdditionalUserInfo,
  getAuth,
  GoogleAuthProvider,
  OAuthProvider,
  signInWithPopup,
  signOut,
  type Auth,
  type AuthProvider,
  type User,
} from "firebase/auth";

/**
 * This identity has no roomstudio account yet, and the web refuses to make
 * one. `message` is display-ready product copy; `providerId` is the raw
 * Firebase id for logs and tests.
 */
export class IdentityNotLinkedError extends Error {
  constructor(readonly providerId: string, message: string) {
    super(message);
    this.name = "IdentityNotLinkedError";
  }
}

/** Apple ID with no account behind it — sign in on iOS first. */
export class AppleIdNotLinkedError extends IdentityNotLinkedError {
  constructor() {
    super(
      "apple.com",
      "That Apple ID isn’t holding any rooms yet. Open the capture app on " +
        "your iPhone and sign in there first — your rooms follow it here.",
    );
    this.name = "AppleIdNotLinkedError";
  }
}

/**
 * Google account with no account behind it. The copy deliberately does NOT
 * promise that signing in on the iPhone will fix it: iOS links Apple only
 * (0094), and Google reaches an iOS-rooted account only when that account
 * already carries a matching google.com credential.
 */
export class GoogleAccountNotLinkedError extends IdentityNotLinkedError {
  constructor() {
    super(
      "google.com",
      "That Google account isn’t holding any rooms yet. Rooms live with the " +
        "account you signed into on your iPhone — sign in with that one.",
    );
    this.name = "GoogleAccountNotLinkedError";
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
 * The one sign-in path. Runs the popup, then the never-create guard: a
 * sign-in that CREATED a user is undone (delete, or sign-out if the delete
 * fails) and refused with `makeError()`. Popup-flow errors (closed popup
 * etc.) propagate to the caller untouched — the button decides what to show.
 *
 * Both providers share this body on purpose: the guard is the security
 * property, and a second copy of it is a second place for it to rot.
 */
async function signInAsReader(
  provider: AuthProvider,
  makeError: () => IdentityNotLinkedError,
): Promise<User> {
  const a = getFirebaseAuth();
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
    throw makeError();
  }
  return credential.user;
}

/**
 * Sign in with the Apple ID that was linked on iOS. Throws
 * AppleIdNotLinkedError — after deleting the just-created user — when this
 * Apple ID has no account yet (see module docstring for why the web must
 * never keep one).
 */
export async function signInWithApple(): Promise<User> {
  const provider = new OAuthProvider("apple.com");
  provider.addScope("email");
  return signInAsReader(provider, () => new AppleIdNotLinkedError());
}

/**
 * Sign in with Google (decision 0094). Same guard, same reason: refuses to
 * create, throws GoogleAccountNotLinkedError after undoing the sign-in.
 */
export async function signInWithGoogle(): Promise<User> {
  const provider = new GoogleAuthProvider();
  provider.addScope("email");
  return signInAsReader(provider, () => new GoogleAccountNotLinkedError());
}

/** Sign out — a real account operation since decision 0051 landed; the
 * account itself lives on, reachable from any device with the Apple ID. */
export async function signOutUser(): Promise<void> {
  await signOut(getFirebaseAuth());
}
