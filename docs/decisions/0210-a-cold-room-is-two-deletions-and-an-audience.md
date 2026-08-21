# 0210 — a cold room is two deletions and an audience

**Date:** 2026-08-21
**Status:** Decided

## Context

Three perception flags shipped built-and-off — mask refinement (0201),
arm selection (0204) and the object-aware residue (0202) — and none had
ever run on a GPU. Every number behind them is offline geometry over
cached masks.

Giving the first of them a live look needs a room that is COLD, and 0201
says why in one line: "the per-object splat cache is checked before any of
this, so turning the flag on changes nothing about a room whose frames are
already reconstructed — 0160's lesson in a new place. The cure is clearing
the per-frame cache, not the knob."

That establishes the principle and stops there. What follows is the
procedure, because the next person to need a cold room should not have to
re-derive it from the source, and two of the four steps are not guessable.

## The procedure

Room: rp7, scene `a71d125f-…`, bundle `223aca8e-…`.

**1. Put the capture back — as a copy, not an upload.** The captures bucket
sweeps at age 1 d, so a preserved room is never in it. `gcloud storage cp -r`
the preserved local bundle straight into
`gs://roomstudio-captures/captures/<bundle_id>/` under operator ADC. 0164 is
the decision; what it does not say is that **the restored objects carry fresh
creation timestamps, so the window is 24 h from the restore, not from the
capture.** Check `bundle.pb`'s timestamp before planning a multi-round lane:
this lane found rp7 already restored by an earlier lane with **six hours
left**, and re-copying to refresh the clock cost 237 MB and three minutes.

Verify the restore by bytes, not by exit code: `gcloud storage du -s` against
the local tree. Here both sides read 248,134,223 B over 1,159 objects.

**2. Delete exactly two things.** Under
`gs://roomstudio-perception-outputs/scenes/<scene_id>/`:

    frames/*/objects.json
    frames/*/splats/**

Both are load-bearing and neither alone is enough:

- **`objects.json` is a whole-frame cache hit that returns before
  segmentation.** Pass 1 reads it and `continue`s
  (`process_receiver._run_census_two_pass`), so a frame that has one is never
  re-segmented, never enters `states`, and cannot be planned at any budget.
  That is 0160's mechanism, and it is why raising a knob is inert.
- **`splats/*.ply` is the per-object cache.** `_reconstruct_one_object`
  existence-checks it first and takes the cached branch, which never
  constructs the refiner. Leaving splats in place gives a run that
  re-segments and still refines nothing.

`splats/` also holds the `.layout.json` and `.mask.npz` sidecars, so the
recursive delete takes them with it — which is what you want: 0201's
rollback note says the supported way to undo a refined run is clearing the
cache, not flipping the flag back.

**Do NOT delete `masks.npz`.** Pass 1 rewrites it for every frame it
re-segments, and `shell_receiver` reads it for the 0089 suppression union.
Deleting it only costs the shell on frames the new sampling does not select.
`roomplan/room.json` is deterministic from the bundle; `manifest.json`,
`shell.json` and `compressed.json` are rewritten by their stages.

On rp7 this is 110 of 128 objects, leaving 18.

**3. Snapshot first, and prove it.** These four captures are the substrate the
whole perception thread regresses against and no copy of the capture exists
anywhere else. Copy the scene prefix to a bench prefix in the same bucket —
bucket-internal, so it costs no egress and the outputs bucket's only
lifecycle rule touches `masks.npz` at 180 d — then compare **name + size +
md5** on every object, not the object count. Restoration is delete-the-prefix
then copy-back, so it also removes whatever the re-drive newly created.

**4. Drive the candidate with an explicit audience.** This is the step
nothing in the repo prepares you for, and it costs two 401s to find.

`tools/reenqueue_scene.py --process-url` will point a task at a tagged
candidate URL, but it leaves the Cloud Tasks OIDC audience unset. Cloud Tasks
then defaults the audience to the target URI — and **Cloud Run rejects a
token whose audience is a tag-prefixed URL**, at the platform, with "The
access token could not be verified" and no app log at all. Measured twice on
`https://ship1---perception-obj-…/process`.

The working shape is an explicit audience of the **base** service URL while
the request goes to the tag:

    url:      https://ship1---perception-obj-<hash>-as.a.run.app/process
    audience: https://perception-obj-<hash>-as.a.run.app/process

which also has to match `RECEIVER_URL` on the candidate, because
`oidc.OIDCVerifier` independently checks `aud == RECEIVER_URL + "/process"`.
So `RECEIVER_URL` stays the base URL. The consequence is worth stating: the
candidate's own `/shell` and `/compress` enqueues go to the base URL and
therefore run on the **serving** revision. That is safe for these three flags
because none of them is read by either stage, and it would not be safe for a
flag that was.

## Why this shape

The two deletions are not a tidy-up, they are the two cache layers, and they
sit at different levels: one keys on the frame and short-circuits
segmentation, the other keys on the object and short-circuits reconstruction.
A run that clears only the outer one re-segments and then hits every splat;
a run that clears only the inner one never gets past pass 1. Both facts are
one line of code each and neither is visible from the flag's own module.

Keeping `masks.npz` is the same reasoning inverted: it is the one per-frame
artifact that is not a short-circuit — nothing cache-hits on it — so deleting
it buys nothing and can cost the shell.

The audience finding is filed here rather than in an infra note because it is
only reachable when you drive a stage at a candidate, and driving a stage at a
candidate is exactly what a cold-room experiment is for. `deploy_perception.sh
--candidate` prints a smoke command for a human with an identity token; it has
nothing to say about Cloud Tasks, which is how every real stage is invoked.

## What would change this decision

- **A planner that enumerates candidates from the per-frame masks** rather
  than from the observation list (0160's own re-open) would make
  `objects.json` non-load-bearing for planning, and step 2 would shrink to
  the splat cache.
- **A `--audience` flag on `tools/reenqueue_scene.py`** would collapse step 4
  to one command. It is a small change and this lane deliberately did not
  make it: the lane's scope is evidence, not tooling, and a tool change wants
  its own test.
- If Cloud Run ever accepts tag-prefixed audiences, step 4's explicit
  audience becomes optional rather than required. The check is one task.
