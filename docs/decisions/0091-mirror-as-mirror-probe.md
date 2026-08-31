# 0091 — Mirror-as-mirror: the depth-trust gate is not a mirror detector

**Date:** 2026-08-08
**Status:** Refuted — probe run, BUILD CUT — the identification premise is refuted and
what remains is a design question, not an implementation one

## Context

Decision 0080's RP-8 walk recorded a product note: mirror splats bake the
scan-time reflection, so a mirror in a rendered room reads as a strange
painting of whatever the phone saw. The operator wants mirrors to read as
mirrors. This session carried a timeboxed probe: can the shipped mirror class
render as a reflective surface instead of a baked splat, using the mirror
depth-trust gate (`nn_rms_m > 0.05`, decision 0082) as the identifier?

## What was measured

Every object in the six preserved LiDAR manifests (the four walk rooms plus
`247003de` / `13bae607`) carrying either the label `mirror` or the
`depth_trust_demoted` flag:

| | count |
|---|---|
| mirror-labelled objects | 5 |
| …of those, depth-trust demoted | **2** |
| demoted objects that are NOT mirrors | **9** |

The nine false positives are ceiling fans (2), curtains (3), chairs (2) and
doors (2). As an identifier the gate scores precision 2/11 ≈ 18% and recall
2/5 = 40%.

**The premise is refuted.** `depth_trust_demoted` is a depth-RELIABILITY
signal, and it fires on everything whose LiDAR return is untrustworthy —
specular glass, thin blades, moving fabric, dark surfaces. Keying reflective
rendering off it would render ceiling fans and curtains as mirrors while
missing three of the five real mirrors. The gate does its own job well
(0082's demotion to the ray path); it is simply not this job.

The reliable identifier is the one already in hand: SAM 3's `mirror` label,
which caught 5 of 5.

## Why the build was cut anyway

Identification is free, but the two remaining halves are not.

**Geometry.** A reflective surface needs a PLANE — center, normal, extent.
Only 1 of the 5 mirrors is placed by `single_view_wall_contact`, i.e. anchored
to a measured wall it could inherit a plane from. The other four are
`depth_fit` (2), `silhouette_fit` (1) and unplaced (1), so their plane would
have to be derived from the object's own transform and extents — the arbitrary
per-reconstruction canonical frame that produced the 0065 face-down episode
and the 0081 axis-mapping work. Deriving a mirror normal from that frame is
the same class of guess, and a mirror pointed the wrong way is worse than a
baked one.

**Rendering, and an honesty question that is the operator's to answer.** A
real planar reflection (three.js `Reflector`) shows the CURRENT virtual scene
— a room reflecting its own reconstruction, including its gaps. A stylized
treatment shows a plausible non-reflection. The baked splat shows what the
camera actually saw. All three are defensible; which one belongs in a product
whose entire claim is that it shows people their real room is a design call,
not an implementation detail. There is also an unverified technical risk: Spark
renders splats through its own shaders and sorting, so whether splats appear
correctly inside a `Reflector` render pass is unknown and would need its own
probe.

Both belong with the reveal-choreography design session decision 0080 already
queued, where the operator is in the room.

## What would change this decision

- The design session settles what "reflective" should look like → the build
  becomes a scoped viewer task, keyed on the `mirror` LABEL (never the
  depth-trust flag), consuming a plane the server emits.
- If it proceeds, the server half is: emit an explicit `surface` descriptor
  (world-space rect) for mirror-class objects anchored to a MEASURED wall, and
  ship nothing for the rest — the same evidence rule the placement path
  already follows. Do not derive a mirror plane from the splat's canonical
  frame.
- If a future capture tier gives mirrors a measured plane directly (RoomPlan
  does not classify mirrors today), the geometry objection weakens and this
  can be reopened on its own.
