# 0240 — the dark tail is a covered lens

**Date:** 2026-08-24
**Status:** Decided (a verdict on the capture app, plus one build)

## Context

Decision 0235 measured that rp6g2's last 28 keyframes are black — mean luma
0.13 to 4.49 against that capture's median of 129.5, 23.4% of the room — and
left the cause open with a sharp question attached: **poses and depth are valid
on those frames.** ARKit kept tracking while the camera produced nothing. 0235
named three candidates — a covered lens, a pocketed phone, or an RGB pipeline
stall — and pointed out that if it is the third, it is a defect in the app real
users run and nobody has looked for it.

That is the question this note answers. It is worth answering because rp6g2 is
the corpus's thin case and every claim resting on it inherits the cause.

## What we tried

Read the preserved bundle (`ea40c579-…`, 124 keyframes) directly, and read the
capture path against it.

**The RGB.** The dark frames are not blank buffers. They are **146–250 kB
JPEGs** — a uniform frame compresses to a few kB, so that is high-entropy
sensor noise. Their channel means run **R ≈ 3× G ≈ 8× B** (f103: 5.30 / 1.57 /
0.53). Rendered with gain, f95 shows **fingers entering frame**, f96 shows a
hand filling it with light leaking past the top, and f97–f123 are the deep red
of light transmitted through skin. Exposure visibly ramps f97 (0.13) → f104
(2.73), and **f108 carries a transient bright event** — mean 11.77, max 66 —
where the hand shifted and a light source leaked in.

**The depth, which is the independent witness.** Through f95 the depth map
carries room structure at 2.1–3.3 m median. **From f96 it is a plane at
0.39–0.59 m filling 100% of the field, flat to ~1 cm RMS**, against 30–100 cm
residual on the frames before it. It holds that distance for 5.7 s while the
phone travels a metre, so the surface is moving *with* the camera. Camera pitch
barely changes across the transition (−13° at f95, −13° at f96), so the phone
was not lowered or pointed at the floor.

**The code.** `CaptureManager.session(_:didUpdate:)` takes `frame.capturedImage`
on the ARKit thread, hops to MainActor, then to `jpegQueue`, where
`CIImage`/`createCGImage`/`jpegData` writes the file.

## What we chose

**Not the app. The lens was covered by the operator's hand** for the last 5.7 s
of a 32.8 s capture.

And, separately, the statistic is now measured on every keyframe and reported at
stop — see 0241 for why it reports rather than refuses.

## Why

The pipeline-stall hypothesis is refuted three independent ways, any one of
which is sufficient:

* **A zero-filled buffer does not render black.** ARKit vends biplanar YCbCr.
  Y=0, Cb=Cr=0 through the video-range matrix gives R=0, **G≈136**, B=0 — mid
  green. The dark frames are red-dominant near-black.
* **A recycled buffer would show another frame's room**, sharp, not noise. And
  the file sizes rule out any uniform content at all.
* **Depth co-varies with luminance frame for frame.** f96 is the transition in
  both. f108's light leak is the tail's brightest RGB *and* its largest depth
  and best planarity. No RGB-side stall can move the LiDAR.

The positive account is fully coherent and needs nothing else: a hand arrives at
f95, closes over the camera at f96, and stays until the capture ends, with
auto-exposure hunting in the dark behind it. Red dominance is the giveaway —
flesh transmits red far better than green or blue, which is the same physics as
holding a finger over a phone flash.

**The distances deserve one caveat.** 0.4–0.5 m is farther than a finger resting
on the lens, and ARKit's depth is unreliable at point-blank range, so the tail's
absolute distances are probably a floor rather than a measurement. Nothing in
the verdict rests on the number — what rests on it is that the surface is
near, flat, full-frame and co-moving, and all four hold at any plausible scale.

**One latent gap found while ruling the app out, and deliberately not fixed
here.** `acceptFrame` appends the `CapturedKeyframe` to `capturedFrames`
synchronously, while the JPEG encode and write happen later on `jpegQueue` and
can both fail — each path logs, counts a failure, and returns without removing
the manifest entry. So the bundle can declare a frame whose file was never
written. That is a **missing** file, not a dark one: api-internal's
declared-blob check (0105) turns it into `failed_incomplete`, and rp6g2 has all
124 JPEGs on disk. The stop-time verification already counts accepted vs
written vs on-disk but does not reconcile them. Recorded rather than fixed
because it is a different failure with a different surface, and no capture has
been observed hitting it.

## What would change this decision

**Nothing about this capture** — it is preserved and immutable, and the reading
is direct rather than inferential.

What would re-open the *class* is **a dark run with room-scale depth behind
it**: luminance collapsing while the LiDAR still sees 2–3 m would mean the RGB
path failed on its own, which is the hypothesis this capture does not support.
0241's logging exists to make exactly that case visible the first time it
happens. A dark run whose depth is near and flat is this one again, and is a
person's hand.

**This does not retract anything drawn from rp6g2.** 0235's reading stands: the
findings are correct measurements of a defective capture, and the defect is now
named. The re-scan 0150 framed as a test remains the cheapest way to replace
that room's contribution to the corpus.
