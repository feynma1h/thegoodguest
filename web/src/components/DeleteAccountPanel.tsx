"use client";

/**
 * Account deletion, from the account menu (decision 0095). App Store 5.1.1(v)
 * requires this path once an app offers Sign in with Apple, and there is no
 * iOS sign-out (0064), so this is the one place a user can end their account.
 *
 * The flow is deliberately three beats rather than one button:
 *   confirm  — states BOTH consequences (everything goes; the phone starts
 *              over) and shows the real room count fetched on open, so the
 *              user sees the size of what they are destroying
 *   working  — the request is running
 *   done     — what actually went, then out
 *
 * Copy lives in lib/account.ts as pure functions, pinned by tests: the
 * honesty of these claims is the product surface, and "review it by reading"
 * is how understated consequence copy survives.
 */

import { useEffect, useState } from "react";

import {
  PHONE_CONSEQUENCE,
  deletionConsequence,
  deletionOutcome,
} from "@/lib/account";
import { getApiClient } from "@/lib/api";

type Phase =
  | { name: "confirm" }
  | { name: "working" }
  | { name: "done"; line: string; finished: boolean }
  | { name: "error"; line: string };

export default function DeleteAccountPanel({
  uid,
  onCancel,
}: {
  uid: string;
  onCancel: () => void;
}) {
  const [phase, setPhase] = useState<Phase>({ name: "confirm" });
  const [rooms, setRooms] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    getApiClient()
      .listScenes(100)
      .then((scenes) => {
        if (!cancelled) setRooms(scenes.length);
      })
      // A failed count is not a reason to block deletion — the copy simply
      // stays numberless (deletionConsequence(null)).
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  const onDelete = async () => {
    setPhase({ name: "working" });
    try {
      const result = await getApiClient().deleteAccount(uid);
      const { done, line } = deletionOutcome(result);
      setPhase({ name: "done", line, finished: done });
      if (done) {
        // The server deleted the identity; the browser still holds its
        // token. Drop it, then reload so every client starts from nothing.
        const { signOutUser } = await import("@/lib/firebase");
        await signOutUser().catch(() => {});
        setTimeout(() => {
          window.location.href = "/";
        }, 2600);
      }
    } catch {
      setPhase({
        name: "error",
        line:
          "That didn’t go through. Nothing was deleted — your account is " +
          "exactly as it was. Try again.",
      });
    }
  };

  if (phase.name === "done") {
    return (
      <div className="px-4 py-4">
        <p className="text-sm font-medium text-ink">
          {phase.finished ? "Your account is closed." : "Still working."}
        </p>
        <p className="mt-2 text-xs leading-relaxed text-ink/55">{phase.line}</p>
        {!phase.finished && (
          <button
            type="button"
            onClick={onDelete}
            className="mt-3 cursor-pointer text-xs font-medium text-accent hover:underline"
          >
            Try again
          </button>
        )}
      </div>
    );
  }

  return (
    <div className="px-4 py-4">
      <p className="text-sm font-medium text-ink">Delete this account?</p>
      <p className="mt-2 text-xs leading-relaxed text-ink/60">
        {deletionConsequence(rooms)}
      </p>
      <p className="mt-2 text-xs leading-relaxed text-ink/60">
        {PHONE_CONSEQUENCE}
      </p>

      {phase.name === "error" && (
        <p className="mt-3 text-xs leading-relaxed text-accent">{phase.line}</p>
      )}

      <div className="mt-4 flex items-center gap-2">
        <button
          type="button"
          onClick={onDelete}
          disabled={phase.name === "working"}
          className="cursor-pointer rounded-full bg-accent px-4 py-2 text-[13px] font-medium text-paper transition-opacity hover:opacity-85 disabled:cursor-default disabled:opacity-60"
        >
          {phase.name === "working" ? "Deleting…" : "Delete everything"}
        </button>
        <button
          type="button"
          onClick={onCancel}
          disabled={phase.name === "working"}
          className="cursor-pointer px-2 py-2 text-[13px] text-ink/60 transition-colors hover:text-ink disabled:opacity-60"
        >
          Keep it
        </button>
      </div>
    </div>
  );
}
