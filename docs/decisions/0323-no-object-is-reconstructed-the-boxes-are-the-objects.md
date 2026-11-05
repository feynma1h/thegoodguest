# 0323 — no object is reconstructed: the boxes are the objects

**Date:** 2026-11-05
**Status:** Decided

## Context

`/process` ran SAM 3 on each selected frame and then SAM 3D Objects on every
detected object, producing a Gaussian splat per object that the room page drew.
The operator decided that every boxed object gets a Claude-made furniture model
instead, that unboxed objects do not appear, and that SAM 3D is not used
anywhere. Reconstruction cost 35–75 s of GPU per object on an L4; its output now
has no consumer in the finished room.

## What we tried

- Skipping SAM 3D only for objects that match a person's box (the earlier
  design). Unboxed objects are also not shown, so SAM 3D would still be paid for
  output nobody draws.
- Leaving the code behind a flag. It is a model load, a thousand lines of
  refinement and placement, and a Dockerfile of weights; a flag nobody sets is
  dead code that keeps costing a cold start.

## What we chose

- `/process` runs SAM 3 only, on the frames the census picks, writes each
  frame's `masks.npz` (the kept masks plus the suppressed-concept union the
  privacy filter and the shell read, decision 0089) and the manifest. SAM 3
  stays because the shell and the privacy filter need its masks; it was
  separable from SAM 3D at the code level.
- Removed: the SAM 3D model wrapper and its lazy loader, `/ready`'s SAM 3D
  state, the reconstruction plan, the per-object loop, the refinement context,
  the scene-level fusion of objects, the contact priors and object colour
  modules that served it, and their tests. `get_sam3d` and the `sam3d` field in
  `/ready` are gone.
- The manifest keeps `"objects": []` so readers that ask for it get an empty
  list, and frame entries carry `masks_gcs_uri` and `mask_count` instead of
  per-object entries. Scans made before this change keep their objects and
  splats; every reader tolerates both (decision 0324).
- `/process` no longer enqueues `/compress`: the stage would always find no
  splat to compress, and it runs on this GPU service. The route stays for
  re-driving old scenes.
- Not changed: the Docker image. SAM 3 is installed into the environment built
  from SAM 3D's environment file, so dropping the SAM 3D clone and its ~7 GB of
  weights is an image rebuild that needs a build and a GPU run to verify. It is
  left, with a comment in the Dockerfile, as the next change.

## Why

Deleting beats flagging: it removes a model load and a large untested-in-future
surface, and the tests that pinned it. Keeping SAM 3 keeps the privacy filter
and the shell exactly as they were.

## What would change this decision

If object splats come back as an option (a premium look, an offline tool), the
code is in git history at the commit before this one; the manifest's `objects`
key and the assets response already carry the shape.
