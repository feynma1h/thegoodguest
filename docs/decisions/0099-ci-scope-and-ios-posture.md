# 0099 — CI scope, and why iOS CI is manual-only

**Date:** 2026-08-08
**Status:** Amended by measurement 2026-08-31 — the conclusion stands, the
argument for it does not. See the block under (a).

## Context

Every suite in this project has been run by hand since May: root Python
(600+10), perception-obj (612), the re-enqueue tool (18), web (143), and iOS
(463). The release-hygiene pass stood up GitHub Actions before the repo's first
push. Python and web were straightforward. iOS was not, and this note is
mostly about iOS.

The complication is structural, not incidental. `TheGoodGuest-Integration`
is the *only* scheme in the project, and it bakes `RUN_INTEGRATION_TESTS=1`, so
the four `UploadSessionClientTests` execute live against deployed api-public on
every single run. That is a deliberate posture — CLAUDE.md's iOS test policy
calls it "fail-closed-live, not fail-open", on the reasoning that a suite which
silently skips its contract tests is worse than one that goes red when the
backend is unreachable.

## What we tried

Three postures were considered for iOS CI.

**(a) Run the suite as-is on a macOS runner, live tests included.** Rejected.

**AMENDED 2026-08-31 — the reason recorded below is WRONG, and (a) stays
rejected on other grounds.** The claim was that the happy-path test charges one
capture against the operator's ceiling, so a handful of pushes a day would lock
them out of scanning their own rooms. The ceiling is real and is 12/day, but it
is keyed **per-UID** — `UploadSessionRepository._quota_ref(user_id)` — and every
one of the four live tests calls `Auth.auth().signInAnonymously()` in its own
body and signs out in teardown. Each therefore runs as a brand-new anonymous
user against an untouched allowance and spends one of *its* twelve. **The
operator's quota is never touched.** The evidence that forced the re-check is
`upload-flake`'s 22 consecutive full-suite runs, which could not have happened
under a shared ceiling. The original claim most likely came from live tests
failing in a way that reads like quota exhaustion; the likelier cause is
`CODE_SIGNING_ALLOWED=NO` leaving Firebase unable to reach the keychain
(`SecItemAdd -34018` underneath, `FIRAuthErrorDomain 17995` above).

**What actually rejects (a), and did all along:**

- `.github/workflows/ios.yml` passes `CODE_SIGNING_ALLOWED=NO`, so the live
  tests cannot reach the keychain and fail before they reach the network. (a)
  would not work as configured, quota or no quota.
- `GoogleService-Info.plist` is gitignored, so a runner has no Firebase config —
  the same blocker recorded under (b), which applies to (a) at least as hard.
- macOS runner minutes bill at a large multiple of Linux on a private repo.
- Every full run creates ~4 orphaned anonymous users. Anonymous-user
  auto-cleanup is off and must stay off (it fires the UID-churn mechanism for
  every user on a schedule), so they accumulate permanently. **This is the cost
  that is genuinely about the arrangement rather than about money**, and it is
  what the original argument was reaching for and got wrong.

The paragraph as originally written follows.

Rejected on a cost that is not about money. Since decisions 0087 and 0098,
`/upload_session` charges two per-UID daily quotas: a mint quota (50/day) and a
**capture ceiling of 12/day**. The happy-path test mints a fresh `bundle_id`, so
it charges one capture per run. A handful of pushes in a day would exhaust the
operator's own capture ceiling and lock them out of scanning their own rooms. A
test suite that can deny its author access to the product is a broken
arrangement regardless of how green it is.

**(b) Run unit tests only, via `-skip-testing`.** Mechanically sound —
`-skip-testing:TheGoodGuestTests/UploadSessionClientTests` cleanly drops
the one class holding the live tests, needs no source change, and leaves the
device build pinned to exactly what is on the phone. Two things still block it
from being a push-triggered gate: `GoogleService-Info.plist` is gitignored, so a
runner has no Firebase config (and the resulting failure looks exactly like a
backend outage — the trap CLAUDE.md already documents for fresh worktrees), and
macOS runners bill at a large multiple of Linux minutes on a private repo.

**(c) Skip iOS CI entirely.** Honest, but throws away the decision along with
the config, so the next person re-derives all of this from scratch.

## What we chose

**(b), wired as `workflow_dispatch` only.** `.github/workflows/ios.yml` is
committed, runs the unit subset via `-skip-testing`, carries the plist-restore
step commented out with the secret name it needs, and states in its header that
it has never executed. Python and web get ordinary push/PR triggers.

Two supporting choices in the Python workflow are worth recording:

- **Three separate Python jobs, not one.** The root suite's collection set is
  pinned by `pyproject.toml` testpaths and the root `conftest.py`, which
  deliberately exclude perception and the re-enqueue tool. Beyond that,
  perception declares `numpy<2` (its base image is pytorch/pytorch:2.3.1) while
  schemas resolves to numpy 2.x — one environment cannot host both without
  taking one of them off the version it ships on.

- **Dependencies are read from the pyprojects at install time**
  (`tools/ci_deps.py`) rather than copied into the workflow. The services are
  flat modules whose pyprojects explicitly say they are not installable, so
  `pip install -e services/api-internal` fails at package discovery and the
  deps have to be extracted some other way. Reading them keeps CI from
  drifting the first time someone adds a dependency.

## Why

The deciding argument for iOS is (a)'s cost of running live tests on an
automatic trigger, and it is worth being precise about why it outranks the usual
"just run the tests" instinct. (Read the amendment above first: the quota
interaction this section originally leaned on does not exist. What survives is
the shape of the argument, not the specific cost it named.) The
live tests are valuable *because* they hit the real contract; that is the whole
point of the fail-closed-live posture. But the property that makes them
valuable in a hand-run — a real call against the real deployed service under
the real quota — is exactly what makes them destructive on a trigger that fires
automatically many times a day. The posture is right for a human running the
suite before a commit and wrong for a machine running it on every push. Keeping
the suite as-is for humans and shipping the skipped subset for machines
preserves both.

The source agreed before we did: `UploadSessionClientTests.swift`'s own header
already reads "Do not enable in CI (no network / plist)". This decision honours
that rather than overriding it.

## What would change this decision

- **A CI-only backend project** removes what is left of the objection to (a):
  the orphaned anonymous users would accumulate somewhere disposable rather than
  in the production identity pool. Note that a service account "with its own
  quota" fixes nothing — the quota was never the problem, and this trigger as
  originally written would have been satisfied without changing anything that
  matters.
- **The plist as a repo secret** unblocks (b) as a push-triggered gate on its
  own, independent of the above.
- **A second scheme without `RUN_INTEGRATION_TESTS`** would make `-skip-testing`
  unnecessary, but it adds a scheme to keep in sync for little gain over the
  flag we already pass.
- If **macOS runner cost stops mattering** (public repo, or the minutes are
  simply accepted), the cost half of (b)'s objection disappears.
