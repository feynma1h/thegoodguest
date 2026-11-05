# 0356 — The room is published all at once, by one merge, with a forty-minute deadline

**Date:** 2026-11-05
**Status:** Decided

## What we chose

Nothing is written to `finish.json` or `furniture.json` until the finish and every boxed piece has a terminal result in `work/`, or `JOB_DEADLINE_S` (40 minutes from the job's start, recorded once in `work/job.json`) has passed. `/furniture-merge` then writes both, furniture first, and is the only writer of either; `/finish` and the piece tasks write only `work/`. This amends the earlier design in which `/finish` wrote `finish.json`. `/finish` also enqueues a delayed merge for the deadline so one hung task cannot block the room; every piece task enqueues a merge when it ends; a second merge finds `work/summary.json` and does nothing. At the deadline a piece still running counts as failed and is absent. A finish that could not be measured is absent. A write is skipped when the existing file carries the same `generated_by` (code sha, vocab and prompt version, models, renderer). Pieces that stand on or hang over another are placed together here, and a neighbour that did not pass turns the rule into plain floor placement. No Firestore writes: absent means not yet.

## Why

A single writer and an idempotent merge make Cloud Tasks retries and duplicate tasks harmless. Placing at the merge is the only point where every passed piece is known.

## Known gaps

The two files are two blob writes, not one atomic write; a viewer fetching between them sees furniture without the finish for a moment. A piece task that finishes after the publish does nothing to the room (a re-drive, 0357, republishes).
