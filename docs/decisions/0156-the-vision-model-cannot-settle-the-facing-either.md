# 0156 — the vision model cannot settle the facing either

**Date:** 2026-08-13
**Status:** Refuted — at the same noise floor as the other four instrument families, with one named confound

## Context

Four geometric instrument families are measured dead on the 180 degree
facing sign (0081, 0104). 0104's truncation-direction result gave the
mechanism: SAM 3D GENERATES the unseen side rather than leaving it empty,
so the splat carries no "this side was observed" signature.

The hypothesis this note tests: **the texture asymmetry survives even
though the geometry asymmetry does not.** The observed side carries the
real photograph; the far side is invented. So rendering the placed splat
from its own source camera under both signs should produce one render
showing what the camera saw and one showing what the model made up — and
asking a vision model which matches the photo is recognition rather than
the pixel correlation tier 2 does and 0081 refuted.

It was argued in session as near-certain: "the question is whether a
vision model can tell a cupboard's doors from its back panel, and it can."
That was a confident-sounding inference of exactly the kind this project
keeps getting bitten by, and it is wrong.

## What we tried

The operator's own walk verdicts give a truth table with known answers:

    rp7 box_01 storage  MUST FLIP   ("cupboard is facing the opposite direction")
    rp7 box_04 bed      MUST FLIP   ("bed is facing the opposite direction")
    rp7 box_00 chair    MUST NOT    (facing_flag true, operator blessed, 0080)
    rp6g1 box_01 chair  MUST NOT    (same)
    spike box_06 chair  MUST NOT    (same)

For each: the placed splat rendered from its own source camera under the
shipped sign and under the 180 degree partner (production's own
`reproject.render_splat`), plus the real photo crop at the same bbox. One
structured call per object, claude-sonnet-5, asking which render shows the
same SIDE of the object as the photograph.

**2 right, 2 wrong, 1 unclear.** Confidences 0.50 to 0.65 throughout —
the model is not confident either, and the band is indistinguishable from
the noise floor every other instrument landed in.

The cupboard is the informative failure. The model's own reason: *"Both
renders show nearly identical point-cloud grid patterns."* Looking at the
strip confirms it — SAM 3D invented a back for that cabinet that carries a
grid of panels much like its front. **The texture asymmetry the hypothesis
rests on is not there**, because the generative model invents plausible
texture along with plausible geometry.

## What we chose

Not built. The route is refuted at the same noise floor as the other four.

## The one confound, named honestly

`render_splat` is a crude point-splat rasteriser — 256 px, subsampled,
nearest-point-wins — and the renders are visibly a sparse dot field rather
than a surface. A proper Gaussian render (the browser has one, via Spark)
would look far better, and the two chairs the model got wrong might go
differently on legible inputs.

That is a real confound and it is why this note says "refuted as
implemented" rather than "dead". But it does not rescue the cupboard,
where the two sides genuinely look alike because one was invented to, and
no amount of render quality changes what SAM 3D put there.

## Why the honest conclusion is to stop rather than iterate

Five instrument families have now landed in the same band: cloud
alignment on sign twins (0081), appearance NCC (0081), per-view
aggregation (0104), the truncation-direction prior (0104), and semantic
recognition (here). They fail for one shared reason, now measured twice
over: **a single-view reconstruction's unseen half is fabricated, and
every one of these instruments is asking that fabricated half a question.**

Iterating on render quality would be trying a sixth variant of an idea
whose premise the cupboard case contradicts directly — the pattern 0104
explicitly warns against.

## What would change this decision

**A complete object.** The union of registered reconstructions (0151)
would give the far side real observed texture instead of invented texture,
at which point this exact probe is worth re-running — it would then be
asking about something that was photographed rather than something that
was imagined. That is the only re-open worth naming.

**Or ask the person.** Stage 2's conversation already proposes and applies
transforms; rotation was descoped in 0133 with a re-open trigger. After
five refuted instruments, "the cupboard faces the other way" from the
person who lives in the room stops looking like a fallback and starts
looking like the correct design: a genuinely ambiguous bit, settled in one
sentence by the only party who actually knows.
