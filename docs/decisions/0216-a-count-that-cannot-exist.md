# 0216 — a count that cannot exist

**Date:** 2026-08-21
**Status:** Decided

## Context

Design spec §8 draws an account-conflict screen: the provider identity the user
just signed in with already owns a different account, and the screen asks which
of two lives this phone should join. Its whole argument is two numbers — the
rooms held by the account being switched TO, and the rooms scanned on this
phone. `AccountConflictView` was built to that design, with both counts
required and no sample defaults, and never rendered. Its only references were
its own `#Preview` and a line in `RootFlowView`'s docstring recording that it
is never presented.

The shipped path is two `.alert`s in `SignInSheet`, which name the provider and
state the real cost and count nothing.

## What we tried

Establishing where each number would come from.

- **`existingRooms`** — the count for the account being switched to. `GET
  /scenes` on api-public is scoped to the token's UID and documents that there
  is no cross-user listing; no route reports anything about an account the
  caller is not. The only way to hold that number is to authenticate as that
  account, which is `switchToExistingAccount` — the exact act the screen exists
  to ask permission for. The conflict credential the SDK hands back is
  single-use, so there is no peek-then-decide ordering either.
- **`thisPhoneRooms`** — the count under the current anonymous UID. Obtainable,
  but only from `GET /scenes`, and the app has no client for it: iOS talks to
  `/captures/{id}/upload_session` and `/scenes/by-bundle/{id}` and nothing else.
  The local upload records are not a substitute — `CaptureReaper` frees a
  record once the user has seen the outcome, so counting them undercounts, and
  a number that is wrong at the moment identity is decided is worse than none.
- **The framing itself.** The spec annotates the choice as one where "the
  not-chosen set is held, recoverable", and the option card promises the
  phone's rooms "stay retrievable for 30 days". Neither is true: the anonymous
  credential is gone (0139's mechanism), and scenes carry no TTL. The Swift had
  already dropped the retention promise and said so in a comment, so what was
  left on screen was no longer the designed screen.

## What we chose

Deleted `AccountConflictView` and its preview. `SignInSheet` keeps the
conflict, which is what 0064 already chose: an explicit choice with the real
cost stated and nothing counted.

`WhySignInSheet` stays, unreferenced, in the file that now carries its name. It
wants the same `GET /scenes` that `RoomsListView` and the recent-rooms strip
want — a fetch somebody will write. That is the line: waiting on a fetch is
staging, waiting on a number that cannot exist is not.

## Why

The screen's only advantage over the shipped alerts is the two counts. One of
them cannot be obtained without performing the action being asked about, and
that is a property of the identity model rather than of how much work anyone is
willing to do: accounts are separate, a credential proves you may become an
account rather than inspect it, and rooms belong to a UID. Fed one real count
and one invented one it would be worse than the alerts, because a number reads
as measured. Fed one count and silence on the other it is a different screen
from the one that was designed, and the remaining delta is framing.

Keeping it compiled and unreferenced was the third option, and it is the one
that had been running: a maintained screen whose docstring asserts a design the
system cannot deliver, sitting in a staged list next to screens that are merely
waiting for a fetch, where nothing distinguishes the two.

## What would change this decision

Server-side scene re-parenting — the backend operation 0064 lists as not being
done, which moves scenes between UIDs. With it the conflict stops being an
either/or and becomes a merge, both counts become facts about accounts the
caller is entitled to, and the screen that asks which life to join is asking
the wrong question anyway. Design it fresh then rather than restoring this one.
