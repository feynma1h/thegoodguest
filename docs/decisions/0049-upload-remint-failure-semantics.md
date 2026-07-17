# 0049 — upload re-mint failure semantics: loop-guard fatal, persist-failure deferral

**Date:** 2026-07-17
**Status:** Decided

## Context

The review-findings cleanup pass flagged three "evaluate and document" items in
`BlobUploadManager.onSessionExpired` (tasks.md entries 74, 76, 78):

1. The 410 re-mint loop guard fatals the bundle when `/upload_session` returns
   URIs identical to the stored ones. Is fatal right, or should it be a bounded
   wait-and-retry?
2. If persisting the freshly-minted record fails (`remint_persist_failed`), the
   error is deferred as transient — and if saves *consistently* fail, the
   cross-launch retry counter never advances, so the bundle retries on every
   launch indefinitely. Is that an unbounded-retry bug?
3. Same question for the staleness-reset save failure
   (`staleness_reset_persist_failed`).

## What we tried

Analysis only — no alternative implementations were built. For (1) the
alternative considered was a bounded wait-and-retry (sleep or defer, then
re-mint again, N times). For (2)/(3) the alternative was escalating a repeated
save failure to `onFatalBlobError`.

## What we chose

Keep all three behaviors as implemented. The rationale is now inline at each
site (marked "Decision 0049"); entries 79–81's silent-`continue` strands in the
same function were real bugs and were fixed separately (routed to
`onFatalBlobError`).

## Why

**Loop-guard fatal (1).** A blob PUT returning 410 means GCS has declared that
resumable session dead. If the server then returns the *same* URIs, re-enqueuing
is guaranteed to 410 again — the identical-URI case is precisely the
Firestore-TTL-lag window where the stale `upload_sessions` doc (7-day TTL,
deletion lag up to ~72 h) is still being served. A bounded wait-and-retry could
only succeed once the TTL fires: days of silent background churn, with no UI,
for a capture whose already-uploaded blobs the age=1d GCS lifecycle rule has
long since deleted anyway (the whole scenario requires a >7-day-old pending
upload). A terminal `.failed` with `remint_returned_stale_uris` surfaces the
problem instead of hiding it.

**Persist-failure deferral (2, 3).** If the store cannot save, escalating to
fatal is impotent: `onFatalBlobError`'s own `.failed` write goes through the
same broken store and would also fail, so nothing durable improves. Deferring
is bounded per launch (at most one counter attempt per bundle per launch via
`transientCountedThisLaunch`, at most `maxRetries` in-process PUT attempts per
blob), and the N=10 cross-launch budget resumes counting the moment the store
heals — retry-forever-while-persistence-is-down is the only state the system
can meaningfully be in, and it self-heals.

## What would change this decision

- **(1)** A server-side re-mint endpoint that force-invalidates the stored
  session (or the F1 `expires_at` work making client-side expiry authoritative)
  would let the client request genuinely fresh URIs instead of fataling — at
  that point convert the fatal into a single forced re-mint.
- **(2)/(3)** Evidence from the field of a device where Application Support
  writes fail persistently but the app otherwise runs — then a user-visible
  "storage problem" surface would be worth building; the retry semantics would
  still stand.
