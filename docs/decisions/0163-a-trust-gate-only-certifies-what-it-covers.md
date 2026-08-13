# 0163 — a trust gate only certifies the population it covers

**Date:** 2026-08-13
**Status:** Decided

## Context

The room-quality thread's conclusions all rest on an offline replica of the
production `RefinementContext` (`outputs/room-quality/roomlib.py`), which
reads the same bundles, masks and splats production reads and is
trust-gated: it "reproduces every shipped view choice and every shipped box
object exactly". The ship lane needed that replica to state, before
deploying, what each room's manifest should become — so that a live re-drive
could be checked against a prediction rather than admired.

## What we tried

Before trusting the replica, the pre-merge code was run through it over the
same cached inputs, as a control: whatever the OLD code produces offline
should be each room's shipped manifest, and anything else is the instrument.

Three objects failed that control. rp7's two mirrors swapped which one ships
and which is suppressed as a `cross_label_duplicate`; rp6g1's two curtains
swapped the same way; and the spike room's window changed its honest reason
from `represented_as_shell_opening` to `insufficient_observations`. Object
counts, placed counts and every other object matched exactly.

The common thread is that all three are FREE objects that reach a fallback:
each is depth-trust demoted (0075's specular-depth gate), which routes them
to the single-view contact-prior path. The replica passed
`get_room_planes=lambda: None`, so `_single_view_contact` returned
immediately (`fusion.py:2220`) and that whole path was dead offline while
production ran it. Production builds the same value in one line —
`contact_priors.extract_room_planes(bundle.plane_anchors)` — from a bundle
the replica already had open for camera poses.

With that wired in, the control reproduces all three shipped manifests
exactly: every remaining difference is `extent_m_sorted[0]` in its 16th
decimal, at zero movement and zero rotation, which is a Mac-vs-Linux
floating-point last bit. Live then reproduced the new code's prediction to
the same limit.

## What we chose

The replica builds real room planes. More importantly: the trust gate's
wording is exactly right and was read too generously. It certifies view
choices and BOX objects, and box objects never touch contact priors — so
the gate could not have caught this, and passing it was never evidence
about free objects.

An instrument that is trusted for a population it was never gated on is
worse than no instrument, because its output looks like a measurement. Two
of these three artefacts were carried into the walk pack the operator was
shown, presented as changes this thread had made. They were not changes.

## Why

The failure is silent by construction. A missing accessor does not raise —
it makes a code path return early, so the instrument produces a complete,
plausible answer that differs from production only on the objects that
needed the thing it lacked. Nothing distinguishes that from a real finding
except a control run, which is why the control is the load-bearing step and
not a formality.

The general rule this buys, stated so the next replica inherits it: a
faithful replica must supply every accessor production supplies, and the
cheapest proof is to run the CURRENT code through it and require the SHIPPED
output back. Any divergence is the instrument until shown otherwise, because
the shipped output is the one thing both sides are supposed to agree on.

Lanes B and D read this same replica. Lane B's whole subject is which view a
box's reconstruction comes from, which the gate does cover; lane D's is
registering two reconstructions of one object, which it does not.

## What would change this decision

Nothing about the rule. The specific fix is superseded the moment production
gains another accessor — the replica must gain it in the same change, and
the control re-run is what proves it did.

If a future thread finds the control diverging on objects it did not touch,
the finding is the instrument, not the code, until a second control says
otherwise.
