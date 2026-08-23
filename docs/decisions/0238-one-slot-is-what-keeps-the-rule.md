# 0238 — one notice slot, rendered in every variant, is what keeps 0224's rule

**Date:** 2026-08-24
**Status:** Decided

## Context

Decision 0224 established the rule — *content goes in the scroll area; only the
action is pinned* — after a screenshot showed home's rooms-trouble line
truncating the app's primary action to **"Scan a ro…"** at
`accessibility-extra-extra-extra-large`.

It fixed the line it owned and named the two it did not: `UploadFailedBanner`
and home's re-entry row, both still stacked in `RootFlowView`'s wrapper `VStack`
outside `HomeView`'s `ScrollView` — "in exactly the position that produced
this", never screenshotted with the pinned action in frame.

## What we tried

Photographing both at AX5, and photographing the shipped structure beside the
replacement so the difference is evidence rather than argument.

0224's prediction is confirmed on both. With the banner stacked outside,
`Label("Scan a room")` renders **"Scan a ro…"** and its support line
**"Takes about two…"**, with the hero clipped behind the button. With the
re-entry row stacked outside, the same truncation, **plus** the second defect
0224 named: a default-`.center` `HStack` put the gold status dot and the
disclosure chevron in the middle of three wrapped lines, the dot reading as
punctuation and the chevron as though it pointed at one word.

Moving both into `HomeView`'s `notice` slot renders **"Scan a room"** and
**"Takes about two minutes"** whole, in the banner case, the re-entry case, and
the two composed — and the action stays legible at every scroll position, top
to bottom of the notice content.

## What we chose

Both surfaces render in `HomeView`'s `notice` slot, and **that slot moved above
the `hasRooms` branch so it renders in every variant** rather than only in the
no-rooms one.

The row is extracted to `Home/ReEntryRow.swift` so it can be previewed and
photographed instead of only read, and it and the banner's headline are
top-aligned against prose that wraps.

## Why

The layout half is 0224's reasoning and needs no restating. What this note adds
is the **structural** half, which 0224 could not see from one caller.

As shipped, `notice` rendered only inside `if !hasRooms`. That is invisible
while the trouble line is its only client — a failed rooms fetch *is* the
no-rooms case. But it means the slot could not carry a notice for a returning
user with rooms, and both surfaces this lane moved are exactly that: the banner
and the re-entry row appear whether or not the strip is populated. A caller
with something to say to a returning user would have found the slot unusable
and put it back in the wrapper `VStack` — **rebreaking the rule by following
it**.

So the rule is only durable if the slot is a genuine home for every notice this
screen carries. One slot, rendered in both variants, is cheaper than asking each
future caller to remember which side of the `ScrollView` they are on — which is
the same argument 0224 made for having a slot at all, applied one level up.

Worth recording separately: **this is now the fifth accessibility defect on this
screen found by screenshot and the fifth that reading missed**, including by
passes that had read 0224 itself. The rule is written down and was still not
enough; only the photograph was.

## What would change this decision

Nothing about the rule or the slot. The open residue is the other direction:
`RoomsListView`, `WaitingView`, `FailureView`, `DoorwayView` and `ProfileView`
have not been through this shot, and any of them that pins an action beside
content in a fixed column has the same defect available. The cheap sweep is one
AX5 pass per screen with the action in frame, not a re-read.
