# 0104 — The 0085 walk: four fixable classes, and rotation's measured evidence limit

**Date:** 2026-08-08
**Status:** Decided
**Relates to:** 0080 (RP-8 walk), 0081 (axis instrument), 0082 (walk classes
2–5), 0085 (consolidated-walk verdicts), 0100 (material-family instability)

## Context

The consolidated acceptance walk (0085) ranked five defect classes across
four rooms. The charter's reframe came from the **paired bed**: rp7 shipped
`splat_axis_resolved=false` + `facing_flag` and the operator said "facing
the wrong direction"; rp6g1 shipped `resolved=true` and they said "looks
okay". The instrument's confidence signal is honest — so the hypothesis
was that the 0.10 margin gate **abstains too often** (5 of 14 box objects),
and the instruction was to attack abstention rather than lower the gate.

All work below replicated the 14 shipped box objects bit-for-bit offline
through the production code paths first (the 0081 trust gate: margins,
resolutions, view counts, cloud-point counts all identical) before
measuring anything.

## What we tried on rotation — and what it measured

**The abstention hypothesis is refuted.** Against known truth, the
instrument's argmax in the sub-gate zone is right 1 time in 3: it would
fix rp7's bed (0.0201) and break rp6g1's chair (0.0738), for a net of
zero, while breaking 0081's pins. Below the gate the two assignments are a
genuine coin flip — which is what the gate is for. Of the five
abstentions, only one (rp7's bed) ships a default the operator called
wrong; the other four ship correct defaults.

Four attacks on the evidence itself, all refuted with measurements:

* **Box-volume multi-frame cloud** (SAM-free, every frame of the capture,
  points inside the measured box). Margins COLLAPSE — 0.2384 → 0.0012,
  0.3383 → 0.0024 — and the spike bed flips to the wrong winner.
* **Per-view scoring, aggregated** (each frame's thin surface scored
  separately, verdicts combined). Breaks 2 known answers, fixes 0.
* **Appearance on the 180° partner**, on the two signs the walk PROVED
  wrong: prefers the wrong answer on both (−0.0077, −0.0014 — noise) and
  prefers the partner at +0.1178 on a chair the operator blessed.
* **The truncation-direction prior** (SAM 3D reconstructs the visible
  region, so mass should be displaced toward the observing camera): not
  separable — wrong cases +1.79/+1.45, ok cases −1.75 to +1.86, complete
  overlap, on centroid offsets of only 0.3–8.5 cm.

The mechanism the first two share is now measured rather than assumed:
**the instrument works because a single-view cloud is a thin surface that
is CORRELATED with the splat's own truncation** — both are the same
visible region — so a wrong rotation cannot nest into it. Adding views
adds surfaces the splat was never truncated to match, and filling the
volume gives every rotation a neighbour. More evidence of the wrong kind
actively destroys the signal.

**So the walk's box-rotation failures separate into two problems, not
one:** ONE abstention that ships a wrong default (rp7's bed), and TWO
*resolved* boxes whose 180° sign is wrong ("the storage front is facing
the wall", "the big table front is facing the wall"). The sign leaf is the
harder problem and now has three refuted instrument families against it
(cloud — 0081; appearance and truncation-direction — here). It keeps the
fixed (+,+) convention, and `facing_flag` stays flag-only for a measured
reason rather than an anecdotal one: promoting it would have broken a
chair the operator approved.

## What we chose to build

* **Splat clipping (class 2).** Uniform scale stands (the RP-8 A/B), so a
  mis-proportioned splat necessarily overshoots its box: measured, 10 of
  14 box objects overflow past 5 cm, worst 0.44 m — the bed the operator
  saw intersecting the table and the chair, in two independent rooms. That
  mass is known-false, because the box is measurement the operator
  verified 9/9 (0076). `build_box_object` declares a `splat_clip` volume —
  the box grown by `PLACEMENT_SPLAT_CLIP_MARGIN_M` — and the viewer
  declines to render outside it. Position, rotation and scale are
  untouched: 0082 was right that moving or rescaling the object would
  falsify a measurement to hide a splat artifact, and declining to draw
  known-false mass does not. The 0.10 m margin is chosen from a sweep, not
  guessed: it removes nothing from 8 of 14 and trims exactly the four
  gross overhangs; at 0.0 m a well-proportioned table with a 3 cm overhang
  loses 60% of its points.
* **Support surfaces take the RENDERED top (class 3).** The walk's lamps
  and TV were already resting exactly on measured box tops. What the user
  sees is the splat: the spike speaker sank 3.3 cm into a table whose
  splat stands 0.033 m proud of its box — the same number to the
  millimetre, which is why class 3 and class 2 are one defect. Contact
  height now follows the rendered top, floored by the measurement (a
  truncated splat must not drag the surface down) and capped by the clip
  margin. Splat-derived surfaces are added for objects no box covers;
  a measured box surface always wins, which answers 0082's v2 objection by
  ORDERING rather than ignoring it. Surfaces are built once, so the pass
  is order-independent.
* **Label scale floor (class 4).** A 0.245 m "television" is a failed
  reconstruction, not a small television. It demotes to honest inventory —
  never a rescale, because there is no measurement to rescale to. Only
  `tv`/`television`: floors for bed, sofa, door and wardrobe were drafted
  and CUT when the only evidence they generated was demoting legitimate
  small-geometry test fixtures.
* **Two vocabulary gaps.** RoomPlan files a nightstand as `storage` where
  SAM says `nightstand`, so rp7's nightstand shipped both as an unmatched
  box and as a free splat — and the lamp and TV resting on it inherited
  the disagreement. Separately, a box object is labelled with its RoomPlan
  CATEGORY, which the cross-label dedup groups did not speak, so `storage`
  could never collapse against `desk` or `cabinet`. Both maps now span
  both vocabularies.
* **`SHELL_MATERIAL_MIN_CONF` 0.6 → 0.75** (0100's recommendation), as the
  default rather than a deploy-env override so offline re-drives and
  production agree on what a shell says. **It does not retro-apply, by
  design:** all four walked rooms already carry shell.json v3, so the
  `--shell` re-drive takes the version-gated redelivery noop and their
  families are whatever was baked before. The raise governs the next shell
  BAKE — a new capture, or a deliberate blob delete. Forcing a re-bake was
  declined rather than overlooked: 0070 requires reference-room
  re-adjudication before material families change, which is the operator's
  call, and leaving materials fixed also isolates this session's placement
  changes for the coming walk.

## Why

Every fix consumes only measured geometry and either declines to render,
demotes, or shifts a bounded amount — the house rule that a guessed
transform is never emitted holds throughout. The rotation work is recorded
as refutations because that is what it produced: four attacks, four
measured negatives, and a sharper statement of where the ceiling is.

## What would change this decision

- **The splat is the bottleneck, and it is now the named one.** A splat
  reconstructed from one view is truncated; that truncation defeats every
  rotation instrument AND causes the overflow that clipping papers over.
  If SAM 3D stops truncating visible regions, class 2's clip goes inert on
  its own and 0081's candidate B becomes viable again.
- A sign instrument that separates 180° twins on real data still has the
  0081 near-tie pin waiting for it, and now two more: the appearance and
  truncation-direction refutations here are pinned by the walk's own
  ground truth.
- The class-5 residue (a cabinet behind a wall) is NOT what the charter
  supposed. Measured: the 0.35 m declip bound never engages, because the
  object's centre projects outside every wall's rectangle so the pass's
  `inside` test fails; and the room-sanity gate does not fire either,
  because the cabinet is INSIDE the measured floor polygon, 2.14 m from
  the nearest corner. Whoever picks it up starts from there, not from the
  bound.
