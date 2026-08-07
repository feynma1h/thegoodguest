/**
 * Pins for the web auth seam (decisions 0051, 0094). The load-bearing
 * invariant: the web is a READER of identity, never a creator — every
 * sign-in must refuse (delete + typed error) any popup that would create a
 * Firebase user, because a web-born account would permanently claim that
 * identity out from under the phone that owns the rooms. 0094 made the rule
 * provider-agnostic, so the guard is pinned identically for BOTH providers
 * — a Google path that quietly skipped it would be the exact regression
 * these tests exist to catch. Also pins the token provider's signed-out
 * semantics (null after auth-state restoration, no interactive fallback)
 * that LiveApiClient's no_local_token error depends on.
 *
 * The firebase/* SDK modules are fully mocked; these tests exercise OUR
 * decisions, not Firebase's.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";

const h = vi.hoisted(() => {
  const auth = {
    currentUser: null as unknown,
    authStateReady: vi.fn(async () => {}),
  };
  return {
    auth,
    signInWithPopup: vi.fn(),
    getAdditionalUserInfo: vi.fn(),
    signOut: vi.fn(async () => {}),
  };
});

vi.mock("firebase/app", () => ({
  // A pre-existing app means initializeApp (and its env requirements)
  // is never reached.
  getApps: () => [{ name: "test-app" }],
  initializeApp: vi.fn(),
}));

vi.mock("firebase/auth", () => ({
  getAuth: () => h.auth,
  signInWithPopup: h.signInWithPopup,
  getAdditionalUserInfo: h.getAdditionalUserInfo,
  signOut: h.signOut,
  OAuthProvider: class {
    scopes: string[] = [];
    constructor(public readonly providerId: string) {}
    addScope(scope: string) {
      this.scopes.push(scope);
    }
  },
  GoogleAuthProvider: class {
    readonly providerId = "google.com";
    scopes: string[] = [];
    addScope(scope: string) {
      this.scopes.push(scope);
    }
  },
}));

import {
  AppleIdNotLinkedError,
  GoogleAccountNotLinkedError,
  IdentityNotLinkedError,
  getCurrentUser,
  getFirebaseIdToken,
  signInWithApple,
  signInWithGoogle,
} from "./firebase";

beforeEach(() => {
  h.auth.currentUser = null;
  h.auth.authStateReady.mockClear();
  h.signInWithPopup.mockReset();
  h.getAdditionalUserInfo.mockReset();
  h.signOut.mockClear();
});

describe("getCurrentUser / getFirebaseIdToken", () => {
  it("waits for auth-state restoration before deciding signed-out", async () => {
    expect(await getCurrentUser()).toBeNull();
    expect(h.auth.authStateReady).toHaveBeenCalled();
  });

  it("yields null (not a throw) for the token when signed out", async () => {
    expect(await getFirebaseIdToken()).toBeNull();
  });

  it("yields the user's token when signed in", async () => {
    h.auth.currentUser = { getIdToken: async () => "token-123" };
    expect(await getFirebaseIdToken()).toBe("token-123");
  });
});

// The never-create guard is provider-agnostic (0094), so the whole suite is
// parameterized. Adding a third provider means adding a row, not a file.
const PROVIDERS = [
  {
    name: "signInWithApple",
    signIn: signInWithApple,
    providerId: "apple.com",
    errorType: AppleIdNotLinkedError,
  },
  {
    name: "signInWithGoogle",
    signIn: signInWithGoogle,
    providerId: "google.com",
    errorType: GoogleAccountNotLinkedError,
  },
] as const;

describe.each(PROVIDERS)("$name", ({ signIn, providerId, errorType }) => {
  it(`requests the ${providerId} provider`, async () => {
    const user = { uid: "uid-1", delete: vi.fn() };
    h.signInWithPopup.mockResolvedValue({ user });
    h.getAdditionalUserInfo.mockReturnValue({ isNewUser: false });

    await signIn();

    const provider = h.signInWithPopup.mock.calls[0][1] as {
      providerId: string;
    };
    expect(provider.providerId).toBe(providerId);
  });

  it("returns the existing user untouched", async () => {
    const user = { uid: "uid-1", delete: vi.fn() };
    h.signInWithPopup.mockResolvedValue({ user });
    h.getAdditionalUserInfo.mockReturnValue({ isNewUser: false });

    expect(await signIn()).toBe(user);
    expect(user.delete).not.toHaveBeenCalled();
    expect(h.signOut).not.toHaveBeenCalled();
  });

  it("deletes a just-created user and refuses with the typed error", async () => {
    const user = { uid: "fresh", delete: vi.fn(async () => {}) };
    h.signInWithPopup.mockResolvedValue({ user });
    h.getAdditionalUserInfo.mockReturnValue({ isNewUser: true });

    await expect(signIn()).rejects.toBeInstanceOf(errorType);
    expect(user.delete).toHaveBeenCalled();
  });

  it("refusals are catchable as the shared IdentityNotLinkedError", async () => {
    // The panel catches the BASE type; a provider error that didn't extend
    // it would fall through to the generic "try again" copy.
    const user = { uid: "fresh", delete: vi.fn(async () => {}) };
    h.signInWithPopup.mockResolvedValue({ user });
    h.getAdditionalUserInfo.mockReturnValue({ isNewUser: true });

    await expect(signIn()).rejects.toBeInstanceOf(IdentityNotLinkedError);
  });

  it("carries the provider id on the refusal", async () => {
    const user = { uid: "fresh", delete: vi.fn(async () => {}) };
    h.signInWithPopup.mockResolvedValue({ user });
    h.getAdditionalUserInfo.mockReturnValue({ isNewUser: true });

    await expect(signIn()).rejects.toMatchObject({ providerId });
  });

  it("signs out (and still refuses) when the delete itself fails", async () => {
    const user = {
      uid: "fresh",
      delete: vi.fn(async () => {
        throw new Error("requires-recent-login");
      }),
    };
    h.signInWithPopup.mockResolvedValue({ user });
    h.getAdditionalUserInfo.mockReturnValue({ isNewUser: true });

    await expect(signIn()).rejects.toBeInstanceOf(errorType);
    expect(h.signOut).toHaveBeenCalled();
  });

  it("propagates popup failures untouched (the button decides what to show)", async () => {
    const popupError = Object.assign(new Error("closed"), {
      code: "auth/popup-closed-by-user",
    });
    h.signInWithPopup.mockRejectedValue(popupError);

    await expect(signIn()).rejects.toBe(popupError);
  });
});

describe("refusal copy", () => {
  it("does not promise the iPhone fixes a Google refusal", () => {
    // iOS links Apple only (0094). Telling a Google user to "sign in on
    // your iPhone" would send them somewhere that cannot help.
    expect(new AppleIdNotLinkedError().message).toContain("iPhone");
    expect(new GoogleAccountNotLinkedError().message).not.toMatch(
      /open the capture app/i,
    );
  });
});
