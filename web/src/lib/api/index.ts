/**
 * API mode switch. NEXT_PUBLIC_API_MODE selects who serves the app's data:
 *
 *   mock        (default) — MockApiClient fixtures; no backend, no auth.
 *   live-local  — LiveApiClient against NEXT_PUBLIC_API_BASE_URL (default
 *                 http://localhost:8080, a local uvicorn api-public) with
 *                 the NullTokenVerifier's "test-uid:dev-user" token.
 *   live        — LiveApiClient against the deployed api-public with a
 *                 Firebase ID token from Sign in with Apple (decision 0051:
 *                 the same account the iOS app linked; signed out, the token
 *                 provider yields null and the client throws its typed
 *                 no_local_token error, which pages render as sign-in).
 */

import { LiveApiClient, type ApiClient, type TokenProvider } from "./client";
import { MockApiClient } from "./mock";

export type ApiMode = "mock" | "live-local" | "live";

export function apiMode(): ApiMode {
  const raw = process.env.NEXT_PUBLIC_API_MODE;
  if (raw === "live" || raw === "live-local") return raw;
  return "mock";
}

function baseUrl(): string {
  return process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8080";
}

const devToken: TokenProvider = async () => "test-uid:dev-user";

const firebaseToken: TokenProvider = async () => {
  // Deferred import keeps the Firebase SDK out of mock/live-local bundles.
  const { getFirebaseIdToken } = await import("../firebase");
  return getFirebaseIdToken();
};

let client: ApiClient | null = null;

export function getApiClient(): ApiClient {
  if (client === null) {
    const mode = apiMode();
    if (mode === "mock") {
      client = new MockApiClient();
    } else {
      client = new LiveApiClient(baseUrl(), mode === "live" ? firebaseToken : devToken);
    }
  }
  return client;
}
