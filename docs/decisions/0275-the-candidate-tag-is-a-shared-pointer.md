# 0275 — the `candidate` tag is one shared pointer, and two lanes can hold it

**Date:** 2026-08-30
**Status:** Decided (observed while deploying; no change made to the script)

## Context

0142 established candidate → smoke → flip for perception-obj because a revision
that fails at run time burns a full 900 s GPU request, and route registration
cannot be checked locally at all. `deploy_perception.sh obj --candidate` creates
the revision with `--no-traffic --tag=candidate`, which is exactly right for one
lane at a time.

This project routinely runs several lanes at once, each in its own worktree, and
they share one Cloud Run service.

## What we tried

Deploying the `/track` candidate on 2026-08-30 found `perception-obj-00089-gij`
already holding `tag: candidate` — another lane's revision, at 0% traffic. The
deploy moved the tag to `perception-obj-00090-wey`.

**`--tag` is a mutable pointer with no owner.** Cloud Run reassigns it silently:
there is no warning, no confirmation, and the traffic list afterwards shows only
the new holder. The displaced revision keeps existing and keeps serving 0%; what
it loses is the URL anyone was pointing at.

The consequence is specific and quiet. `tools/segment_frames.py` and
`tools/track_frames.py` both default `CANDIDATE_URL` to
`https://candidate---perception-obj-…`, and both pin the OIDC audience to the
STABLE `RECEIVER_URL` precisely so the candidate host can vary. So a probe
dispatched with `--candidate` after another lane deploys **authenticates
correctly and runs against the wrong revision**, and every artifact it writes
looks exactly like a normal result.

## What we chose

**Record it; do not change the script.** The default is correct for the common
case and for the flip workflow that CLAUDE.md documents, and adding a per-lane
tag by default would leave the printed flip command naming a tag nobody expects.

What a concurrent lane should do instead is pass its own tag — `--tag=sam31`
gives `https://sam31---perception-obj-…`, which no other deploy will take — and
point `CANDIDATE_URL` at it. That costs one environment variable and removes the
collision entirely.

## Why

**The failure is invisible on both sides.** The displaced lane gets no error: its
next probe simply runs somewhere else. The displacing lane gets no error either,
because from its side everything is correct. Nothing in the artifacts records
which revision produced them — `/segment` and `/track` both write a scene-scoped
prefix with no revision in it.

**And the tag is what a probe addresses, not the revision.** 0260 made Cloud
Tasks the only way to reach this platform-gated service, and pinned the audience
to `RECEIVER_URL` so a candidate host would work at all. That fix is what makes
the tag freely reassignable without breaking auth — so the same property that
made candidate probing possible is what makes this silent.

**This is the same class as the worktree rules in CLAUDE.md.** Two sessions
sharing one tree nearly produced a false green in July; two lanes sharing one
tag is the same shape one level up, in infrastructure rather than in the
filesystem. The existing rule — give every session its own worktree — has an
obvious counterpart: give every concurrent lane its own tag.

## What would change this decision

**A run whose result depends on which revision answered.** This deploy's probe
is `/track`, a route only the new revision has, so a mis-addressed call would
404 rather than mislead — the safe direction, and luck rather than design. A
lane probing a route that exists on BOTH revisions with different behaviour
behind a flag gets a plausible wrong number instead, and that is the case worth
the guard.

**The cheap durable fix is provenance, not process.** If probe output recorded
the revision that produced it — `K_REVISION` is already in the environment of
every Cloud Run container — the collision would be detectable after the fact
instead of unnoticeable. That is a one-line addition to a response body and it
would have made this note unnecessary.
