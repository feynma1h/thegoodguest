"use client";

/**
 * Account deletion, opened from the account menu (decision 0095). App Store
 * 5.1.1(v) requires this path once an app offers Sign in with Apple, and
 * there is no iOS sign-out (0064), so this is the one place a user can end
 * their account. Decision 0361 moves it out of the menu into its own alert
 * dialog: an irreversible choice deserves the whole of someone's attention.
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

import { Dialog, SheetTitle } from "@/components/ui/Dialog";
import { PillButton } from "@/components/ui/spring";
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

export default function DeleteAccountDialog({
  open,
  uid,
  onClose,
}: {
  open: boolean;
  uid: string;
  onClose: () => void;
}) {
  const [phase, setPhase] = useState<Phase>({ name: "confirm" });
  const [rooms, setRooms] = useState<number | null>(null);

  useEffect(() => {
    if (!open) return;
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
  }, [open]);

  // Closing abandons a half-made choice rather than leaving it armed for the
  // next open; a request already running is never interrupted.
  const close = () => {
    if (phase.name === "working") return;
    if (phase.name === "done" && phase.finished) return;
    setPhase({ name: "confirm" });
    onClose();
  };

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

  return (
    <Dialog open={open} onClose={close} label="Delete this account?" alert className="max-w-[460px] p-8">
      {phase.name === "done" ? (
        <>
          <SheetTitle>{phase.finished ? "Your account is closed." : "Still working."}</SheetTitle>
          <p className="mt-4 text-[16.5px] leading-[1.55] text-ink-2">{phase.line}</p>
          {!phase.finished && (
            <div className="mt-7 flex flex-wrap gap-2.5">
              <PillButton variant="danger" onClick={onDelete}>
                Try again
              </PillButton>
              <PillButton variant="ghost" onClick={close}>
                Close
              </PillButton>
            </div>
          )}
        </>
      ) : (
        <>
          <SheetTitle>Delete this account?</SheetTitle>
          <p className="mt-4 text-[16.5px] leading-[1.55] text-ink-2">
            {deletionConsequence(rooms)}
          </p>
          <p className="mt-3 text-[16.5px] leading-[1.55] text-ink-2">{PHONE_CONSEQUENCE}</p>

          {phase.name === "error" && (
            <p role="alert" className="mt-4 text-[14.5px] leading-relaxed text-accent-deep">
              {phase.line}
            </p>
          )}

          <div className="mt-7 flex flex-wrap gap-2.5">
            <PillButton variant="danger" onClick={onDelete} disabled={phase.name === "working"}>
              {phase.name === "working" ? "Deleting…" : "Delete everything"}
            </PillButton>
            <PillButton variant="ghost" onClick={close} disabled={phase.name === "working"}>
              Keep my account
            </PillButton>
          </div>
        </>
      )}
    </Dialog>
  );
}
