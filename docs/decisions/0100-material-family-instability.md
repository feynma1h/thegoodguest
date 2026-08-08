# 0100 — Material-family instability is the gate floor, not the evidence

**Date:** 2026-08-08
**Status:** Decided (observability shipped; gate change recommended, not applied)

## Context

The 0089 privacy re-drive re-baked `f3d70236`'s shell and produced a
disquieting result, recorded as residue in CLAUDE.md: `wall_06`'s evidence was
byte-identical across the two bakes — 18,329 texels, 5 frames, the same measured
albedo — and yet its material family moved from `None` to `"tile"`. The floor
moved `"stone"` → `"tile"` in the same re-drive. Both returned confidence
exactly **0.6**, which is exactly `SHELL_MATERIAL_MIN_CONF`.

That is alarming on its face: identical input, different output, in something
shipped to users as a property of their room. This note is the diagnosis.

## What we tried

Read the path end to end (`shell_material.py`) and measured the confidence
distribution across every preserved real shell.

**Mechanism — three facts that compose.**

1. **The call is not deterministic.** `classify_family_via_api` omits
   `temperature` deliberately: non-default sampling params are rejected (400)
   on `claude-sonnet-5`, as the module docstring records. So the call runs at
   the model's default sampling, which is not greedy. Two identical requests
   may legitimately return different answers. The docstring is explicit that
   "determinism rests on the receiver's write-once noop" — and a **re-bake
   bypasses exactly that noop**, which is what the 0089 re-drive did.

2. **The prompt asks for a self-reported probability** ("confidence is your
   probability (0 to 1) that the chosen family is correct"). Self-reported
   confidence is the least calibrated number a language model produces, and it
   clusters on round values.

3. **The gate admits the floor.** `raw_conf >= SHELL_MATERIAL_MIN_CONF` means a
   0.6 answer passes. Semantically that is the correct reading of a minimum,
   but it means the admitted set includes precisely the answers the model
   flagged as least certain.

**Measurement.** Every family admitted across the two preserved LiDAR rooms
(`247003de`, `13bae607`), n = 7:

    0.60  painted    247003de   <- the unstable one
    0.85  painted    13bae607
    0.90  wallpaper  13bae607
    0.96  wallpaper  247003de
    0.97  wallpaper  247003de
    0.98  wallpaper  13bae607
    0.98  wallpaper  247003de

**The interval (0.60, 0.85) is empty.** Six answers are decisively confident;
one sits exactly on the floor. The distribution is bimodal: the model is either
sure, or it emits the hedge value. Nothing observed lands in between.

## What we chose

**Shipped: log admissions, not only rejections.** The gate previously logged
only the gated-OUT case, so a family admitted at the floor left no trace — which
is why this was findable only by diffing two `shell.json` files by hand. An
admission now logs its confidence and is tagged `AT_GATE_FLOOR` when it sits at
or below the threshold. Pure observability, no behavioural change, so it needs
no re-adjudication under 0070's residue rule.

**Recommended, NOT applied: raise `SHELL_MATERIAL_MIN_CONF` from 0.6 to 0.75.**
Env-only — it is already read from the environment, so this is a value change on
the next deploy, not a code change.

## Why

The instability is not evidence-driven and not a bug in the estimator. It is the
sampling non-determinism of fact 1, surfacing through the boundary of fact 3, on
answers that fact 2 already labelled as guesses. The evidence was never the
unstable part; the model's certainty was.

The recommendation follows from the empty interval. On the observed data,
raising the floor to 0.75 would drop exactly one admitted family — the single
0.60 answer, the one measured to be unstable — and retain all six confident
ones. There is no observed answer between the two that a higher floor would
cost us.

The direction of error is also safe, which is what makes this recommendable
without re-adjudication anxiety. Raising the gate can only turn a family into
`None`, and `None` is not a degraded guess: it is the module's own
LOAD-BEARING FALLBACK RULE — the plane renders clean matte in its **measured**
albedo. Albedo is measurement and is unaffected by this gate. So the worst case
of raising the floor is a correct-but-plainer surface, while the worst case of
leaving it is a confidently wrong material that flips between bakes.

Why not applied here: this session carries a no-deploy constraint, and 0070's
residue rule says material-inference changes should be re-adjudicated on the
reference room first. Raising a threshold is conservative enough that the
adjudication is cheap, but it is still the operator's call and it belongs with a
deploy.

**n = 7 is a small sample.** The claim worth relying on is the qualitative one —
the model hedges at a round floor value and those answers are the unstable ones
— not the precise cut point. 0.75 is chosen as the midpoint of an empty region,
not as a tuned optimum.

## What would change this decision

- **A larger sample that populates (0.60, 0.85).** If real rooms start producing
  0.7-confidence answers that adjudicate as *correct*, 0.75 is costing real
  families and the cut point should move down.
- **A deterministic call.** If `claude-sonnet-5` (or its successor) accepts
  `temperature: 0`, fact 1 disappears, re-bakes become reproducible, and the
  gate floor stops being a coin-flip admission — though a 0.6 answer would still
  be a low-confidence one, just a *consistently* low-confidence one.
- **Dropping self-reported confidence entirely** in favour of self-consistency
  (N calls, majority wins, disagreement ⇒ `None`). Strictly better signal, and
  it would supersede the threshold approach — but it multiplies the cost of a
  call the design deliberately makes once per plane per room lifetime.
- **If families are ever trusted as stable product data** — surfaced in the UI
  as a claim about the room rather than as a rendering hint — the write-once
  noop stops being sufficient stability and this needs the self-consistency
  treatment, not a threshold.
