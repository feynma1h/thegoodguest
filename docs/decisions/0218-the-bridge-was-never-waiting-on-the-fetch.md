# 0218 — the bridge was never waiting on the fetch

**Date:** 2026-08-22
**Status:** Spent — `QRBridgeView` was deleted 2026-09-01 with the append path it waited on (0294). The finding stands; the surface it was about is gone.

## Context

The scenes-client lane was briefed as "one fetch, four surfaces": write the iOS
client for `GET /scenes` and wire the four surfaces built against it — the
returning-home recent-rooms strip, `RoomsListView`, `WhySignInSheet`, and
`QRBridgeView`. `RootFlowView`'s docstring said the same thing, listing all of
them as wanting "the same GET /scenes fetch, plus trigger points".

Three of the four do. The fourth does not, and reading it is what shows that.

## What we tried

Establishing what `QRBridgeView` would consume from a list of the caller's
rooms. Its whole surface is: an eyebrow, a decorative QR glyph, one guest line,
and `onScan: () -> Void`. Nothing on it is room-shaped, and its own docstring
names its blocker: the QR encodes nothing because no deep-link infrastructure
exists, and the transport is universal links, which need the associated-domains
entitlement.

Design spec §9 labels it `FUTURE · QR / DEEP-LINK BRIDGE (WEB → PHONE)` and
describes the flow as the desk handing a session back: "A universal link (or QR
when scanning from a desktop) opens the app straight into a targeted rescan for
that room, already signed in."

That sentence is the answer. The room the bridge is about is named *by the
link*. The desk knows which room it wants a corner of; the phone learns it from
what it is handed. A list of the phone's own rooms tells it nothing it needs —
and could not, since the desk's request is for one specific room and arrives
with its own identifier.

## What we chose

Left `QRBridgeView` staged and unwired, and corrected `RootFlowView`'s docstring
so the staged list names its real blocker instead of a shared one. Three
surfaces consume the fetch; the bridge is not one of them.

It was re-verified at AX5 by screenshot rather than by reading — it is one of
the two screens in this app that have actually failed AX5 — and its "Scan the
code" action is reachable by scroll. That is the only claim this lane makes
about it.

Not deleted, which is where this differs from decision 0216. That note removed
`AccountConflictView` because the number it was designed around cannot be
obtained *by construction* — accounts are separate, and a credential proves you
may become an account rather than inspect it. The bridge is blocked on an
entitlement and some infrastructure. Both are real blockers; only one of them is
permanent, and a screen waiting on Apple Developer Program enrollment is
waiting, not lying.

## Why

A brief that groups four surfaces under one dependency is a claim about all
four, and three of them being right is exactly the condition under which the
fourth goes unchecked. Wiring the bridge to `RoomsStore` would have been easy
and would have compiled: hand it a room, let it show a title. It would also
have invented a dependency the design does not have, and left a screen that
appears wired while still doing nothing, which is worse than the honest
placeholder it is today — the placeholder at least says what it is waiting for.

The general form, which is what makes this worth recording: "these surfaces are
all blocked on X" is a premise to test per surface, not a plan. The cost of
testing it is reading four files.

## What would change this decision

Associated-domains entitlement plus a deep-link route, at which point the
bridge gets wired to whatever the link carries — still not to `GET /scenes`.
The one thing that would genuinely put it on this fetch is a design change:
a bridge that opens on a *chooser* ("which room is the desk asking about?")
rather than on a room the link already named. That would be a different screen
from the one in §9, and worth arguing for on its own terms rather than reaching
for it because a fetch happens to exist.
