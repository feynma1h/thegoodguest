# 0294 — the append path is two features and neither ships

**Date:** 2026-09-01
**Status:** Decided

## Context

Three surfaces in the design ask for the same thing and call it by two names —
"add more" and "targeted rescan":

- **Review, thin coverage.** "I've got the bones, but a few gaps. Worth another
  minute?" with **Add more** as the primary action.
- **After the reveal.** A bad region is set aside rather than rendered broken; a
  targeted rescan returns to capture pointed at just that spot, and the design's
  own phrase for what makes it work is *"the app remembers what's already good."*
- **The QR bridge** (§9, decision 0218). The desk hands that request back to the
  phone: scan a code, open straight into a targeted rescan of the named room.

None of it is built. `CaptureManager.startCapture()` mints a fresh `bundleId`
and clears frames, plane anchors and the output directory;
`capture_bundle.proto` has no append concept; api-public claims a `bundle_id`
atomically and refuses a second claim.

The question arose while establishing why the QR bridge could not be built. The
bridge is not blocked on an entitlement or on a URL to encode — it is blocked on
this, because a link whose destination does not exist is a transport to nowhere.

## What we tried

Nothing was built. What this note records is the reading that came out of
scoping it, and the ruling that followed.

**The plumbing is the small part.** Resuming a bundle across iOS, the proto, the
upload contract and perception is four layers of ordinary work.

**The coordinate frame is the real problem.** Every camera pose in a bundle is
expressed in the ARKit session's world frame, and the backend places objects
using those poses (0052). Appended frames must land in the *same* frame or they
describe a different room. That splits the feature in two, and the halves are
not comparable:

- **Add more at review.** `stopCapture()` calls `arSession.pause()` rather than
  tearing the session down, so the world origin is still there. This is close to
  "do not reset, resume". Tractable, and it is the half with a UI branch already
  built and waiting — `ReviewView`'s `thinCoverage` variant.
- **Targeted rescan later.** The phone must re-localise into a room it captured
  hours or days ago. That needs `ARWorldMap`: capture it, persist it, reload it,
  wait out `.relocalizing`. **No world map is saved anywhere today** —
  `getCurrentWorldMap` appears nowhere in the tree. And relocalization can
  simply fail: different light, moved furniture, a rearranged room. The failure
  is not rare and it has no obvious honest fallback, which for this product
  matters more than the engineering does.

## What we chose

**Ruled out, 2026-09-01, by the operator.** The append path is not being built,
in either half. `docs/punchlist.md` G1-08 was deleted rather than annotated,
per the punchlist's own rule.

Two surfaces are stranded by this and are named here so the ruling is not
rediscovered as a bug:

- **`QRBridgeView` can never get a route.** It is reachable today from nothing
  but the screenshot gallery, which is the state 0237 ruled on for
  `WhySignInSheet`: give it a route or delete it, do not tidy it. The only thing
  that could have given it a route was the append path. It is now a delete
  candidate rather than a staged one.
- **`ReviewView`'s `thinCoverage` branch is permanently dormant.** It is built,
  `thinCoverage` is never set true, and its primary action is "Add more" — the
  thing that does not exist. It is photographed by the gallery and marked
  BUILT AND UNREACHABLE there.

Neither is deleted by this note. Both are flagged; deleting a designed surface
is the operator's call and 0237 is the precedent for how that call reads.

## Why

The ruling is the operator's and does not need defending here. What is worth
recording is the shape of the thing, because it is the part that will not be
obvious to whoever next reads the design spec and sees "Add more" as a primary
action in a shipped screen.

**They are two features wearing one name.** The punchlist entry treated them as
one item, and so does the design language. One is a session that was paused and
could be resumed; the other is a spatial re-localisation problem with a real
failure rate. Anyone scoping "the append path" from the spec alone will price
the first and inherit the second.

**The cheap half is genuinely cheap, and that is a trap rather than an
argument.** It would light up a built UI branch for a modest cost — and it would
also make "add more" a thing the product does, which is exactly the promise the
expensive half has to keep everywhere else. Shipping the review-time half alone
means a person can add to a capture in the sixty seconds before they send it and
never again, which is a harder thing to explain than not offering it at all.

## What would change this decision

Two independent triggers, either sufficient:

- **A capture that is measurably too thin to use, often enough to matter.** The
  review branch exists because someone expected this; `thinCoverage` has never
  been set true, so the need is asserted and not measured. If real captures
  start failing on coverage, the review-time half becomes a fix for an observed
  problem rather than a feature in search of one.
- **Relocalization stops being the hard part.** If a future ARKit makes
  re-localising into a saved room reliable enough to promise — or if the room
  shell itself becomes the anchor, so a rescan registers against measured
  geometry rather than against a saved feature map — the expensive half loses
  the failure mode that made it not worth it.

Until then the honest position is the one the code already takes:
`ReviewView`'s secondary action is named `rescan`, not "add more", and nothing
in the app implies additive behaviour.
