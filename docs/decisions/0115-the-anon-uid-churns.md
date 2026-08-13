# 0115 — The anonymous UID churns, and the stand-down drains one room per launch

**Date:** 2026-08-13
**Status:** Measured on hardware; the churn's CAUSE is open

## Context

Decision 0036 states the invariant that anonymous auth caches its UID and
**never churns it** — sign in only when `currentUser` is nil — because a
churn silently disowns every room the device has captured. Decision 0074
built the survival behaviour for when it happens anyway (a by-bundle poll
403 is the `notOwned` terminal; the phantom row stands down and is
acknowledged in `DismissedBundles`). Both were believed adequate. During
an operator-guided session the 16 Pro produced a pill —
"One room is on its way — check on it" — that returned after **every**
relaunch, which reads exactly like acknowledgment failing to persist.

## What we tried

The operator stopped tapping so the store would not drain further, and the
device state was pulled intact: `upload_sessions` (12 records) and the
`StagingHooks` breadcrumb log. Then every scene in Firestore was grouped
by `user_id`.

**Finding 1 — the acknowledgment persists; the backlog was draining.** The
reaper's own scan line is a perfect instrument: `reaper-scan ids= acked=`
went `10 → 11 → 12 → 13 → 14 → 15 → 16` across the relaunches, strictly
monotonic, and `ea40c579` logged `acked=false → skip` at 08:16:59 and
`acked=true` at 08:17:12 — one launch apart, with the tap in between. But
0074's `foreignBundleToAcknowledge` returns **one** bundle, so exactly one
foreign record clears per launch. Four unacked foreign records therefore
cost four force-quit/relaunch/tap cycles, each one re-showing the pill.

**Finding 2 — the phone's anonymous UID has churned twice.** Ownership of
every ready scene, by uid:

| uid | rooms | dates |
|---|---|---|
| `cHfMlUL…` (now the Google account) | 7 | 2026-07-26 → 08-05 |
| `j9UJyV6s…` | 3, incl. the hero source `ce68e24f` | 2026-08-08 |
| `u4AmDs2Vd…` | 2 | 2026-08-12 → 08-13 |

All three minted their bundles **from this phone** — the records are on its
disk. So the 16 Pro was `cHfMlUL`, became `j9UJyV6s`, and became
`u4AmDs2Vd`, orphaning each period's rooms as it went. The pill storm was
not ancient June debris; three of the four newly-acked bundles were the
phone's *own* rooms from five days earlier, made foreign by a churn.

The cause is **not** established. The container demonstrably survived
(June-era records are still on disk), so the app was never deleted — the
keychain went without the container. Candidates: the `CODE_SIGN_ENTITLEMENTS`
drop used for personal-team signing altering the keychain access group;
the provisioning re-issuance; a keychain purge. Not asserted.

## What we chose

Record both findings and fix neither in this session. The immediate
operational consequence was acted on instead: the Google link's
switch/keep fork was decided as **switch**, because `cHfMlUL` — the
account Gate B attached an email to — *is* the phone's own original
identity, so switching is the phone recovering what the churn took rather
than adopting a stranger's account. That restored the 7-room walk corpus
at the cost of two test scans, and made 6 retained records owned again.

## Why

The drain rate is a real defect but a mild one, and it is only visible on
a device whose identity has changed — which is supposed to be impossible.
Fixing the drain (acknowledge the whole foreign set in one stand-down)
without understanding the churn would make the symptom quieter while the
cause kept manufacturing orphaned rooms. The ordering matters: a user who
loses their rooms and gets a *smoother* dismissal experience has been
served worse, not better.

Recording the churn without a cause is deliberate. Three plausible
mechanisms exist and the honest position is that we measured the effect,
not the mechanism; a note asserting the entitlements theory would be read
by the next session as established and would misdirect the investigation.
What the note *can* fix is the trap: the phantom-room class has a root
cause upstream of 0074, and 0074 is a survival mechanism, not a cure.

A collateral benefit worth keeping: switching made 6 records owned,
acked and terminal at once, which is the only condition under which the
launch-scan **positive** reclaim leaf can fire — the doorway path acks and
reclaims in the same instant, so the scan normally never sees such a
record. One relaunch then produced `code=200 status=ready → reclaim` six
times and `403 → retain` six times, verifying both directions of 0084's
table in a single scan.

## What would change this decision

- **The churn's cause is found.** The next device session should read the
  installed app's entitlements and keychain access group before and after
  a rebuild, and check whether `AuthManager.signInIfNeeded` saw a nil
  `currentUser` at first launch after the 08-08 and 08-12 installs. If the
  entitlements drop is the cause, the personal-team workaround is
  destroying user identity every time it is applied — which would make it
  far more expensive than "never commit this" implies, and would be a
  reason to prioritise Apple Developer Program enrollment beyond the
  reasons already recorded.
- **Enrollment lands** and the entitlements workaround retires; if churns
  stop with it, that is the answer.
- **The drain is fixed** (acknowledge the whole foreign set per launch, or
  acknowledge on the scan rather than on a tap) — after the cause is
  known, not before.
- **Sign-in becomes mandatory before capture**, which would make anonymous
  identity non-load-bearing and retire this whole class.
