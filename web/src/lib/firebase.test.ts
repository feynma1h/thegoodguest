/**
 * Pins for the web auth seam (decision 0051). The load-bearing invariant:
 * the web is a READER of identity, never a creator — signInWithApple must
 * refuse (delete + typed error) any sign-in that would create a Firebase
 * user, because a web-born account would permanently claim the Apple ID
 * out from under the phone that owns the rooms. Also pins the token
 * provider's signed-out semantics (null after auth-state restoration, no
 * interactive fallback) that LiveApiClient's no_local_token error depends
 * on.
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
}));

import {
  AppleIdNotLinkedError,
  getCurrentUser,
  getFirebaseIdToken,
  signInWithApple,
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

describe("signInWithApple", () => {
  it("requests the apple.com provider", async () => {
    const user = { uid: "uid-1", delete: vi.fn() };
    h.signInWithPopup.mockResolvedValue({ user });
    h.getAdditionalUserInfo.mockReturnValue({ isNewUser: false });

    await signInWithApple();

    const provider = h.signInWithPopup.mock.calls[0][1] as {
      providerId: string;
    };
    expect(provider.providerId).toBe("apple.com");
  });

  it("returns the existing user untouched", async () => {
    const user = { uid: "uid-1", delete: vi.fn() };
    h.signInWithPopup.mockResolvedValue({ user });
    h.getAdditionalUserInfo.mockReturnValue({ isNewUser: false });

    expect(await signInWithApple()).toBe(user);
    expect(user.delete).not.toHaveBeenCalled();
    expect(h.signOut).not.toHaveBeenCalled();
  });

  it("deletes a just-created user and throws AppleIdNotLinkedError", async () => {
    const user = { uid: "fresh", delete: vi.fn(async () => {}) };
    h.signInWithPopup.mockResolvedValue({ user });
    h.getAdditionalUserInfo.mockReturnValue({ isNewUser: true });

    await expect(signInWithApple()).rejects.toBeInstanceOf(
      AppleIdNotLinkedError,
    );
    expect(user.delete).toHaveBeenCalled();
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

    await expect(signInWithApple()).rejects.toBeInstanceOf(
      AppleIdNotLinkedError,
    );
    expect(h.signOut).toHaveBeenCalled();
  });

  it("propagates popup failures untouched (the button decides what to show)", async () => {
    const popupError = Object.assign(new Error("closed"), {
      code: "auth/popup-closed-by-user",
    });
    h.signInWithPopup.mockRejectedValue(popupError);

    await expect(signInWithApple()).rejects.toBe(popupError);
  });
});
