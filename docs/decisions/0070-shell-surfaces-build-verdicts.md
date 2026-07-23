# 0070 — Shell-surfaces build verdicts: closure calibration, inference amendments, and the person-contamination finding

**Date:** 2026-07-23
**Status:** Decided (records the 0069 build's measured deviations from its
brief, the adjudication outcome, and one finding that qualifies a 0069
claim. 0069 remains the design authority; this note is the build's
verdict layer, the way 0068 was to 0067.)

## Context

The 0069 build (generated parametric materials + envelope closure) ran
its V1/V2 offline probes on the reference capture (scene `f3d70236`), the
operator adjudicated the inferred materials before deploy, and the full
chain then deployed and V3-walked on the live stack (`perception-obj-00032-km5`,
`api-public-00016-qer`). Four facts measured during the build amend the
brief's a-priori spec, and one adjudication finding qualifies a claim
0069 made. Recorded here so the next session doesn't re-derive them or
mistake deliberate deviations for drift.

## What we chose (deviations from the brief, all deliberate)

- **`SHELL_JOIN_MAX_GAP_M` defaults to 0.5, not the brief's a-priori
  1.5.** At 1.5 the floating curtain-plane fragment (member 16, 1.26 m
  above the floor) seams the MAIN WALL across a fabricated 1.45 m run,
  and mutually-justifying fragment pairs appear; every real corner on
  the reference capture closes at ≤ 0.3. The brief chartered exactly this
  ("calibrate the four knobs against this capture"). Pinned by
  `test_shell_closure_real_data.py`.

- **A fifth closure knob the brief didn't name:
  `SHELL_FLOOR_CONTACT_TOL_M` (0.15).** The brief's fragment filter says
  "no floor contact within gate" — but the floor-drop gate (2.0 m)
  cannot BE that gate: everything under 2 m would then participate and
  the filter would never fire. Participation-contact (a fragment's
  detected bottom already within 0.15 m of the floor) and
  extension-permission (a structural wall may be extended down ≤ 2.0 m)
  are different quantities and got separate knobs.

- **The brief's "temperature 0" is unsupported on `claude-sonnet-5`** —
  non-default sampling parameters return 400 on that model. The vision
  call omits temperature and explicitly disables thinking (the model's
  silent default is adaptive); determinism rests on the receiver's
  write-once noop with `MATERIAL_VERSION` + model recorded in the doc,
  and structured outputs (`output_config.format`) provide the
  constrained JSON the brief wanted.

- **Evidence crops are single-frame rectified re-samples (~2.5 mm/px),
  not texel-grid excerpts.** The 2 cm observation texels carry no
  material micro-texture; "rectified evidence crops" was implemented as a
  re-sample of the best-observing frame over the highest-weight tiles,
  square in world space (anisotropic stretch would corrupt
  plank-direction gradients), gated at `SHELL_EVIDENCE_MIN_OBS = 0.8`
  per-tile observation. This gate is what makes family classification
  honest — a half-synthetic tile would feed the classifier invented
  pixels, the wrong-specific failure the fallback rule exists to prevent.

## The person-contamination finding (qualifies 0069's privacy claim)

Adjudication surfaced that `wall_03`'s observed pixels are the operator's
mother (present during capture, in front of the real wall patch):
"person" is not in the SAM prompt vocabulary, so nothing excluded her,
and the plane's measured albedo (#899fbf) is her, not the wall. The
family gate held (one qualifying crop, classification below the confidence
bar → null), but:

- **0069's "moots the shell half of the person-privacy gap" is
  QUALIFIED, not void.** Baked person PIXELS no longer ship (true — no
  textures exist in the v2 contract), but a person can still contaminate
  a plane's measured ALBEDO, and their image reaches the evidence crops
  sent to the vision API. Person detection/masking remains the board-4
  fix, now with a concrete manifestation on the reference room.
- The anchor GEOMETRY verdict stands — the plane is a measured wall
  patch; only its observation is contaminated.

## Adjudication outcome (the 0069 re-open clause did NOT fire)

Floor (#c8c1b7, stone @ 0.60 offline / 0.65 on the deployed re-drive —
same family, same albedo; the confidence variance is expected
model-level non-determinism, not a code difference) and main wall
(#aab9c3, painted @ 0.75) both read true to the operator. One extension
request recorded: the floor's rectangular stones — tile pitch + grid
orientation are measurable from the rectified crops by the same
instrument class as plank direction (periodic gradient structure /
autocorrelation) and would extend `material.params {}` without a contract
change. Deliberately NOT built (0069 keeps pattern treatment out of v1 —
"a wrong pattern breaks recognition worse than a clean matte"); recorded
as the first candidate when the material dict next grows.

## Why

Every deviation traces to the same two masters the brief itself served.
**Measured-over-assumed:** the join gate, the contact tolerance, and the
crop gate are all calibrated against the one real capture rather than
trusted from the brief's a-priori numbers — the standing posture for
every SHELL_* knob. **Honesty made structural:** the crop gate and the
fallback rule both exist to keep the classifier from ever reasoning over
invented pixels, and the person finding is the same principle catching a
case the design didn't anticipate — measured evidence can be a person,
and the honest response is to name the gap, not paper over it.

## What would change this decision

- A capture where real corners need > 0.5 m closure re-opens the join
  gate's default (per-capture calibration is the standing posture).
- Person masking landing (board 4) deletes the contamination residue and
  could re-admit `wall_03`-class planes to full inference.
- The material dict growing pattern params (tile pitch first) is the
  designed extension path — 0069's "extending `material {}`, never
  replacing it."
