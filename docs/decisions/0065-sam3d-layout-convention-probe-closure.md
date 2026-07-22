# 0065 — SAM 3D layout conventions: probe closure (conjugate wxyz, pytorch3d camera basis, arbitrary canonical frames)

**Date:** 2026-07-22
**Status:** Decided (closes 0063's probe; supersedes 0052's two flagged assumptions)

## Context

Decision 0063 recorded the measured verdict (systematic ~90° gravity
deviation — conventions wrong as-shipped) plus a fix candidate from an
offline A/B (xyzw + identity basis, 21.0° vs shipped 96.9°), and refused
to ship it blind because of a documented confound: Meta's `make_scene`
applies `_fix_gaussian_alignment` (a Y/Z swap) somewhere in their compose
path while we export raw splats, so part of the error might live between
the splat frame and the layout frame. This session ran the controlled
probe 0063 required: BOTH a near-zero metric AND visually correct
rendered orientation.

## What we tried

1. **Read Meta's source** (facebookresearch/sam-3d-objects at the commit
   the image clones; pytorch3d pinned at `75ebeea`). Findings, each
   checked against the pinned code, not docs: `make_scene` composes the
   raw `get_xyz` coordinates — the same coordinates `gs.save_ply` writes
   — through `SceneVisualizer.object_pointcloud`, which builds a
   pytorch3d `Transform3d`. `Transform3d` acts on ROW vectors
   (`points @ R`), so the effective column-vector local→camera rotation
   is `R(q)ᵀ` for the wxyz-read quaternion; and `make_scene`
   independently rotates per-splat covariances by
   `quaternion_multiply(quaternion_invert(q), q_g)` — the two paths
   agree exactly. `_fix_gaussian_alignment` turned out to be a
   default-off video-rendering helper (maps a Z-up frame to the Y-up
   turntable; `det = +1`), unused by the demo compose path: **the 0063
   splat-frame confound is dead** — no alignment is missing between our
   exported splat and the frame the layout rotation acts on.
2. **Extended the offline A/B to the dimensions 0063's grid missed.**
   The original grid varied {order} × {diagonal basis} × {canonical up}
   but never CONJUGATION and never non-diagonal bases. Brute force over
   {wxyz, xyzw} × {conj, no-conj} × all 24 proper signed-permutation
   bases × 6 canonical axes on the recorded real observations (raw
   rotations from the manifest's `layout_prior.raw_rotation`, camera
   poses from the preserved bundle): global winner **wxyz + conjugate +
   identity basis** at median 6.7° (12 upright observations) — with
   0063's candidate at 20.9° exposed as a duality twin of the truth
   minus the conjugation.
3. **Per-object physical checks** (the decisive table). Paired each
   observation's canonical splat extents (which axis is thin/long) with
   its raw rotation and checked where each axis lands in world under
   each hypothesis: verdict scores 6/6 (door and cabinet vertical at
   |cos| = 1.00, curtain 1.00, artwork 0.99) vs 1/6 for 0063's candidate
   (bed on end, door flat on the floor) and a catastrophic bed failure
   for the shipped chain.
4. **Visual probe.** A three-way lineup of the real bed/curtain splats
   in /viewer plus offline top/front rasters: the bed lies flat face-up
   ONLY under the verdict; a yaw-sensitive relative-geometry check
   (curtain plane normal vs the bed→curtain line: 20° verdict, 75°
   shipped, 60° candidate) confirms the full rotation, not just the up
   axis.
5. **Cross-frame consistency probe** — the accidental second discovery:
   the same physical object reconstructed from two frames carries world
   rotations 90–180° apart under EVERY convention. SAM 3D's canonical
   object frame is per-reconstruction ARBITRARY (the generator samples
   it; the layout rotation compensates). Verified independently by the
   probe objects' canonical extents: the bed's up is canonical −Z, the
   door's height is canonical +X — there is no shared semantic frame.
6. **The identity-basis near-miss, caught by the first real-user look.**
   The five instruments above converged on identity basis — and shipped
   a room whose beds, lamp, and chair rendered 180° flipped (duvet
   face-down; confirmed by slab color asymmetry on 4/4 sign-checkable
   objects) while doors/cabinet/curtain stood correct. Identity and
   diag(−1,1,−1) differ by 180° about camera-Y, which preserves every
   axis LINE — all five instruments were provably blind to the
   difference (for portrait captures even the line-angle VALUES nearly
   coincide). The sign-sensitive discriminator that settled it: the
   model's own layout TRANSLATIONS. B·t_layout must point from the
   camera at the triangulated (convention-independent) fused center;
   diag(−1,1,−1) scores dot 0.94–1.00 on all five placed objects,
   identity scores negative on all five, CV in between. Production
   rotations were separately confirmed to match the offline chain to
   0.03°, exonerating the pipeline — the error was in the verdict
   itself.

## What we chose

- `extract_layout` reads wxyz and **conjugates** (the model's quaternion
  maps camera→local; placement composes local→camera). Matrix-form
  rotations transpose for the same reason.
- `_SAM3D_CAM_TO_ARKIT_CAM = diag(−1, 1, −1)` — the layout camera frame
  is the **pytorch3d camera convention** (+X left, +Y up, +Z forward),
  the frame the pytorch3d-native tdfy training stack works in; not the
  CV pointmap frame 0052 assumed, and not the identity this probe first
  concluded (see try 6). The constant stays as the named seam.
- **Fusion stops averaging rotations and raw scales across
  observations** (they are relative to per-reconstruction canonical
  frames); a cluster ships the best member's rotation + scale, strictly
  paired with the splat it renders. Positions and metric extents (ray
  path) still fuse across frames — those are physical quantities.
- The quality metric `gravity_deviation_deg` (fixed canonical up — a
  quantity that does not exist) is replaced by
  **`min_axis_to_vertical_deg`**: for boxy furniture standing normally,
  SOME canonical axis should be plumb; near-zero = coherent rotation.
- **Layout sidecar**: each fresh reconstruct writes
  `{splat}.layout.json` with the RAW model fields; per-object cache hits
  re-run `extract_layout` on it at read time. Before this, a cache hit
  dropped the rotation entirely (`rotation_source: "none"`), so any
  budget-split scene silently lost orientations for cache-carried
  objects; storing RAW fields means a sidecar can never go stale against
  a future convention change.
- Real-data regression pins (`test_layout_conventions_real_data.py`) in
  three sign-sensitivity tiers: axis-LINE pins at achieved accuracy
  (door 2.5°, cabinet 1.7°, curtain 4.8°, artwork 6.2°, chair 14.9°,
  bed 20.7°), SIGNED semantic-up pins (bed duvet face and chair +Z must
  point UP — the identity twin sends both negative), and
  TRANSLATION-DIRECTION pins (dot ≥ 0.90 under the production basis AND
  < 0 under identity, so the pin can never pass vacuously), plus
  discriminator tests proving 0052's shipped chain and 0063's candidate
  fail the bed by >45°.

## Why

0063's insistence on the visual half was vindicated three times over:
the single-axis metric alone had crowned a wrong candidate (21° was the
best score a convention-with-one-wrong-link could reach on an aggregate
the probe showed to be ill-posed); the confound it named was real in
spirit — not a missing splat transform, but the nonexistence of a shared
canonical frame, which invalidated the metric's design AND fusion's
rotation averaging; and even the probe's own five-instrument convergence
shipped a line-blind twin of the truth that only a human looking at the
rendered room caught. The durable lesson: every instrument in the kit
must be classified by what it CANNOT see (line metrics can't see signs;
sign metrics can't see yaw), and closure requires at least one
instrument per error dimension — the translation-direction test now
covers signs geometrically, and the regression pins encode all three
tiers so no single-blind-spot regression can pass quietly.

## What would change this decision

- A SAM 3D release that changes the pose decoder's parameterization or
  the layout frame — the named seams (`LAYOUT_QUAT_ORDER`,
  `_LAYOUT_ROTATION_IS_CAMERA_TO_LOCAL`, `_SAM3D_CAM_TO_ARKIT_CAM`) are
  the update points, and the real-data pins will fail loudly.
- A future SAM version with a semantically canonicalized object frame
  would let the metric mean more and could restore cross-observation
  rotation fusion (Markley over compatible frames).
- Per-object extents work (the conversation fast-follow) may want the
  min-axis metric refined per category (a bed's plumb axis is its thin
  one; a door's is its long one) — the manifest keeps enough provenance
  (`layout_prior.raw_rotation`) to recompute anything offline.
