# 0099 — CI scope, and why iOS CI is manual-only

**Date:** 2026-08-08
**Status:** Decided

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

**(a) Run the suite as-is on a macOS runner, live tests included.** Rejected on
a cost that is not about money. Since decisions 0087 and 0098, `/upload_session`
charges two per-UID daily quotas: a mint quota (50/day) and a **capture ceiling
of 12/day**. The happy-path test mints a fresh `bundle_id`, so it charges one
capture per run. A handful of pushes in a day would exhaust the operator's own
capture ceiling and lock them out of scanning their own rooms. A test suite that
can deny its author access to the product is a broken arrangement regardless of
how green it is.

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

The deciding argument for iOS is (a)'s quota interaction, and it is worth being
precise about why it outranks the usual "just run the tests" instinct. The
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

- **A CI-only backend project or a dedicated CI service account with its own
  quota** removes the whole objection to (a). The live tests could then run on
  every push without touching the operator's ceiling. This is the real fix.
- **The plist as a repo secret** unblocks (b) as a push-triggered gate on its
  own, independent of the above.
- **A second scheme without `RUN_INTEGRATION_TESTS`** would make `-skip-testing`
  unnecessary, but it adds a scheme to keep in sync for little gain over the
  flag we already pass.
- If **macOS runner cost stops mattering** (public repo, or the minutes are
  simply accepted), the cost half of (b)'s objection disappears.
