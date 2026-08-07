/**
 * The words account deletion uses (decision 0095), as pure functions so the
 * honesty of the claims is pinned by tests rather than reviewed by eye.
 *
 * Two claims here are load-bearing and easy to get wrong:
 *
 *   1. WHAT SURVIVES. Nothing does. Saying "your rooms" while conversations
 *      and reconstructions also go would understate it; the copy names all
 *      three because all three are erased.
 *   2. WHAT HAPPENS TO THE PHONE. The account is the iPhone's account. When
 *      it is gone, the capture app has no identity to return to and mints a
 *      fresh anonymous one on its next launch — a new, empty account. Users
 *      deleting from the web must be told that, because the phone is where
 *      they will notice it and the web is where they decided it.
 */

import type { AccountDeletionResult } from "./api/types";

/** Plural-aware noun phrase for a room count ("7 rooms", "1 room"). */
export function roomPhrase(count: number): string {
  return count === 1 ? "1 room" : `${count} rooms`;
}

/**
 * The consequence sentence shown before the irreversible button. `rooms` is
 * null while the count is still loading — the copy stays truthful by not
 * naming a number it doesn't have yet.
 */
export function deletionConsequence(rooms: number | null): string {
  const subject =
    rooms === null
      ? "Every room you've scanned"
      : rooms === 0
        ? "This account"
        : `${roomPhrase(rooms)}`;
  const verb = rooms === 0 ? "goes" : "go";
  return (
    `${subject} — and every reconstruction, measurement and conversation ` +
    `in ${rooms === 0 ? "it" : "them"} — ${verb} permanently. ` +
    `This cannot be undone.`
  );
}

/** The second consequence: what the user's phone does afterwards. */
export const PHONE_CONSEQUENCE =
  "Your iPhone starts over: the capture app opens to a new, empty account. " +
  "Signing in again gives you a fresh start, not your rooms back.";

/**
 * What to say once the server has answered. A partial pass is NOT a failure
 * and must not be reported as one — the identity is deliberately still alive
 * so the caller can resume, and saying "something went wrong" would send the
 * user looking for damage that does not exist.
 */
export function deletionOutcome(
  result: AccountDeletionResult,
): { done: boolean; line: string } {
  if (!result.deleted) {
    return {
      done: false,
      line:
        "Some files are still being removed. Nothing is half-deleted — " +
        "your account is intact until it finishes. Try again in a moment.",
    };
  }
  const { rooms, conversations } = result.counts;
  const parts = [roomPhrase(rooms)];
  if (conversations > 0) {
    parts.push(conversations === 1 ? "1 conversation" : `${conversations} conversations`);
  }
  return {
    done: true,
    line: `Gone — ${parts.join(" and ")}, and everything measured from them.`,
  };
}
