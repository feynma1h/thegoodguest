# 0089 — Person as a suppression-only SAM 3 concept

**Date:** 2026-08-08
**Status:** built, deployed (`perception-obj-00036-l9l`), and live-verified
end-to-end on the person-carrying capture

## Context

Decision 0070 recorded the privacy gap in its sharpened form: "person" is not
in the object vocabulary, so anyone in the room during a capture is observed as
if they were the surface behind them. 0069 removed baked textures from serving,
which stopped person PIXELS from shipping — but albedo is measurement, not
inference, and it kept shipping. The named manifestation was scene f3d70236's
`wall_03`, whose measured albedo is the operator's mother lying in front of
that wall patch.

The operator chose the approach: make "person" a SAM 3 concept that is
SUPPRESSION-ONLY.

## The decision

`person` joins the segmentation prompt. `sam3.py:54` splits the prompt on
commas, so the concept list is the seam and the cost is one extra class pass.
Every detection carrying a suppressed label is partitioned back out
immediately, and the only thing that survives is a mask union used to exclude
those pixels from surface evidence.

Suppression deliberately rides mechanisms that already existed:

- masks.npz gains a `suppressed` union beside `masks`; `shell_receiver` ORs it
  into the exclusion mask 0066 already applies to furniture, so albedo
  evidence loses those pixels for free;
- when person-free evidence runs thin, 0069's EXISTING gates fire — no crops →
  family None, too few observed texels → albedo None → the honest neutral. No
  new degrade path was invented.

The one genuinely new mechanism is at the evidence crops, and it earns its
place: a crop is what gets sent to the material-inference model, and "those
pixels were unobserved and filled with the median color" is not good enough
there. A tile a person stood in is disqualified FOR THAT FRAME, and the tile
falls back to a person-free frame or yields no crop. The check runs inside
`_rectify_crop` at crop resolution (~2.5 mm/px) rather than on the ~2 cm texel
grid used to rank tiles, because the crop is the surface that actually leaves
the process.

## The risk this fix introduces

The segmenter is now told to find people. That puts a person exactly one
careless call site away from being reconstructed, placed, deduped-into, and
inventoried — and from there reachable by api-public's `scene_facts`, whose
entire world is the manifest's `objects[]`. A behavioural test would not catch
it, because the fake segmenters in the existing suites return no people.

Three pins contain it:

1. **End-to-end, both production paths** — a person is segmented, never
   reaches SAM 3D, and appears nowhere in `objects.json` or the manifest.
   Asserted by scanning the documents as TEXT, not by field: a label leaking
   into a provenance or reason string is just as much a leak.
2. **An AST pin** — every `segment()` call site in `process_receiver.py` must
   be given `segmentation_prompt(...)` and must call `partition_detections`
   within 12 lines. This is the pin that survives a future third call site.
3. **A Dockerfile assertion** — `privacy.py` is a deferred import, so a missing
   COPY would pass `/health` and every probe and then silently ship people
   again. That is worse than a crash, because the pipeline keeps working. The
   build asserts the default concept is armed in the image.

## What the fix itself stores, and why that is acceptable

Suppression persists a person-shaped boolean mask in `masks.npz`, in the
outputs bucket, under the `scenes/*/frames/*/masks.npz` 180-day lifecycle
(0086) — a retained silhouette where none existed before. Weighed and
accepted:

- it is a silhouette, no pixels, strictly less identifying than the RGB frames
  the pipeline already read (those live in captures and sweep at 1 day);
- it is never served. api-public signs only `splat_gcs_uri` values from the
  manifest's `objects[]`, and a person is never in `objects[]`. `masks.npz`
  appears in the manifest only as an unsigned `gs://` provenance string;
- the alternative — not persisting it — means every warm `/shell` re-drive
  must re-run SAM 3 on every frame to rediscover the exclusions, turning a
  seconds-long shell run into a GPU job. Persisting the union is what makes
  suppression survive the cache, which is the whole point.

If retention ever needs to shrink, the narrow lever is a separate, shorter
lifecycle on the suppressed union — not on masks.npz as a whole, which the
refinement path depends on.

## Measured, on the real capture

Offline replication of f3d70236's shell reproduced every shipped albedo and
observed-fraction EXACTLY (floor #b7b3a9, wall_03 #616161, wall_04 #5d647c,
wall_05 #b2ab9b, wall_06 #adb9c8), which is what makes the delta below
trustworthy. Person masks were hand-labelled over the three complete frames
containing a person (40, 124, 152) as a stand-in for SAM's — no GPU offline.

- **80.4% of the person's pixels were eligible as surface evidence before this
  change.** Existing object masks (the bed the person is lying on) covered only
  10–30% per frame. The gap was not mostly-covered-already.
- `wall_03` — 0070's named plane — carries 451 person-contaminated texels; its
  albedo moves #616161 → #5a5a5c once they are suppressed.
- The floor carries 3,732; albedo #b7b3a9 → #b7b4a9, observed fraction
  0.8872 → 0.8285.
- The other three walls are untouched: the person does not project onto them.

Two honest notes. The albedo deltas are small because the weighted median is
robust and the person is a minority of each plane's evidence — the point is
that the shipped number no longer contains person pixels at all, not that the
color moved far. And the crop-rejection path was NOT exercised by this
capture's real data: the contaminated frames were never the best-observing
frame for any crop tile, so crop sources were unchanged. That path is pinned by
unit tests only until a capture exercises it.

The current `wall_03` albedo is #616161, not 0070's recorded #899fbf: the scene
was re-driven 2026-07-24 with a different completed-frame set, which reshuffled
which plane carries which evidence. The contamination is the same; the value
moved.

## Live, on the deployed revision

f3d70236 was re-driven on `perception-obj-00036-l9l` with the three person
frames' `objects.json` + `masks.npz` deleted (splat caches retained), forcing
real SAM 3 segmentation with the concept armed.

**SAM found the person in all three frames** — `suppressed=1 labels=['person']`
on 40, 124 and 152 — and the shell consumed the unions (144,131 / 201,285 /
239,244 px). The hand-labelled stand-ins had been 1.2–1.5× larger than SAM's
actual masks, so the offline numbers were conservative in the right direction.

The measured result is **larger than the offline estimate predicted**:

| plane | albedo | observed fraction | texels |
|---|---|---|---|
| wall_03 | #616161 → **#50504f** | 1.0000 → **0.6603** | 936 → 618 |
| floor | #b7b3a9 → #b7b4a9 | 0.8872 → **0.8286** | 24171 → 22576 |
| wall_04 / wall_05 / wall_06 | unchanged | unchanged | unchanged |

**A third of wall_03's measured surface evidence was a person** (34% of its
observed texels). The offline probe under-read this because a hand-drawn
polygon left neighbouring frames covering the same texels; SAM's real masks
removed them outright. The floor's observed fraction landed at 0.8286 against
the offline prediction of 0.8285.

**Degrade lock confirmed on real data, the strongest form available:** the
`masks` stacks the re-segmented frames wrote are **bit-identical** to the ones
they replaced (0 differing pixels across all three), and the kept labels and
their ORDER are identical, so every per-object splat cache hit. The partition
removed exactly the person and perturbed nothing else. SAM 3 is deterministic
here; that is now measured, not assumed.

## An unrelated finding this re-drive surfaced

Material FAMILY assignments are not stable across invocations at the confidence
gate. `wall_06`'s evidence was byte-identical before and after (18,329 texels,
5 frames, same albedo) yet its family moved None → "tile"; the floor moved
"stone" → "tile". Both came back at confidence exactly 0.6 —
`SHELL_MATERIAL_MIN_CONF` — so they are sitting ON the gate, where the call is
a coin flip and 0070's "rectangular stone" floor is a defensible either way.
Not caused by suppression (the evidence for wall_06 did not change at all), but
it means a re-baked shell can ship a different family than the one the operator
adjudicated. Worth its own look before families are trusted as stable product
data.

The same re-drive was also f3d70236's FIRST run on the 0081/0082 code (it was
last driven 2026-07-24; those re-drives covered only the four LiDAR walk
rooms), so its manifest moved 24 → 21 objects with placed 7 → 8. That is the
cross-label dedup collapsing the artwork/painting confusable group and the wall
anchoring pass landing — `wall_normal` appears in `constraints_applied` for the
first time, and every dropped object was an UNPLACED inventory entry. Verified
not to be this change: masks bit-identical, per-frame detections identical.

## What would change this decision

- A live warm re-drive of a person-carrying capture with fresh frame caches
  gives SAM's real person masks and replaces the hand-labelled measurement.
  Note that cached frames keep their pre-0089 masks.npz, so an existing scene
  only gains suppression when its `objects.json` + `masks.npz` are deleted and
  re-segmented (per-object splat caches survive — kept-list ordering is
  unchanged, which is itself pinned).
- `PERCEPTION_SUPPRESSED_CONCEPTS` is the widening seam if capture-time
  findings demand more concepts (screens showing faces, pets, documents). Empty
  reproduces pre-0089 behaviour exactly.
- Suppression is per-frame and positional, not a plane-level veto. If a future
  finding shows a person can dominate a plane's evidence in a way the texel
  gate does not catch, a plane-level rule becomes the next question.
