# 0243 — the flip is three assertions, not one command

**Date:** 2026-08-25
**Status:** Decided

## Context

`deploy_perception.sh obj --candidate` ends by *printing* two commands: an
`update-traffic --to-latest` and a `move_serving_tag`. Every candidate-mode
perception deploy since has been finished by pasting them.

That framing is the defect. A flip is not one action; it is one action plus a
set of preconditions that nothing checks, and on this service two of those
preconditions were quietly false at the same moment.

## What we tried

Nothing was tried. Both were caught by reading the live service between the
smoke and the flip — the same window decision 0200 was caught in, which is
itself worth noting: this is now three separate defects found by looking at
production state after the candidate is up and before traffic moves.

**One — `--to-latest` inherits its target.** `perception-obj` accumulates
0%-traffic revisions, and on 2026-08-25 the newest was not a stale build but
the ship lane's deliberate flag ladder from 0211/0212:

| revision | flags in env |
|---|---|
| `00069-nep` | none |
| `00070-vaf` | `MASK_REFINE` |
| `00071-cof` | `MASK_REFINE` + `ARM_SELECT` |
| `00072-pox` | + **`OBJECT_AWARE_RESIDUE`** |

`status.latestReadyRevisionName` was `00072-pox`. The residue flag is parked by
operator ruling (0212) — its supply change resamples away from the frames mask
refinement depends on. So the printed command, run from a clean read of the
runbook, would have shipped the one flag the deploy existed to exclude, on a
service where nothing downstream would have contradicted it.

**Two — the flip orphans the outgoing image.** The repository's
`cleanupPolicyDryRun` is unset; the policy deletes for real. It keeps
`serving`/`buildcache` by tag plus the 3 newest `perception-obj` versions and
deletes the rest **at any age**. `faa005c8…` — the image the then-serving
`00062-hum` pins — was 5th by recency and protected only by its `serving` tag.
Moving that tag to the incoming image is what the flip *is*, and it drops the
rollback target out of the keep set in the same stroke. `00062-hum` is a
scale-to-zero GPU revision that pulls its image on cold start, so the named
rollback would have survived only until the next policy run.

## What we chose

The flip is three assertions, and none of them is optional:

1. **Name the target; do not inherit it.** Assert
   `status.latestReadyRevisionName` is the revision you just smoked, then
   `--to-latest`. Not `--to-revisions=<name>=100`, which re-creates the traffic
   name-pin that cost the 2026-05 silent no-op the script's own comment
   records.
2. **Pin what you are leaving, before you leave it.** Tag the outgoing image
   `serving-rollback-<revision>` *before* moving `serving`. This is 0200's
   one-off idiom for `00044-m5p` promoted to a standing step, and it carries
   0200's sharp edge with it: the Keep rule matches on tag PREFIX, so the hold
   is owed back once the new revision is trusted.
3. **Tag the digest the revision pins**, read back from the revision, not the
   timestamped tag the build pushed. 0200's rule, restated because it is the
   third member of the same set.

Applied on 2026-08-25: `serving-rollback-00062-hum` was added to `faa005c8…`
before the flip, and the target was asserted to be `00074-var`.

## Why

The two hazards look unrelated — one is about which revision, one is about
which image — but they have a single cause: **the script hands over a command
where it should hand over a procedure.** A printed command carries no
preconditions, so the preconditions live only in whoever is reading, and this
project's own convention is that operator memory is not a durable home.

They also fail in the same direction, which is the part that makes them worth a
note rather than a comment. Neither produces an error. `--to-latest` onto the
wrong revision deploys successfully and serves happily; the flag it adds is
visible only to someone who diffs two revisions' env. An orphaned rollback
image is invisible until the day you need it, which is by definition the worst
day to discover it. Decision 0190 already states the general form — "a cleanup
policy has no idea what Cloud Run is serving" — and this is the same sentence
one step later: *a flip command has no idea what it is replacing.*

The ladder is not a mess to clean up, either, and that is why the cure is an
assertion rather than a sweep. Those 0%-traffic revisions are the ship lane's
evidence for 0212, deliberately kept. A service that holds experiments will
keep having a latest-ready revision nobody wants to serve.

## What would change this decision

If `deploy_perception.sh` grows a `--flip` mode that performs all three
assertions itself, this note becomes the specification for it rather than a
procedure to remember, and the printed-commands hand-off can go. That is the
right end state; it was not built here because this lane owned production
traffic and not the deploy tooling's shape.

If Cloud Run ever gains a first-class "promote this revision" verb that names
its target explicitly, assertion 1 collapses into it.
