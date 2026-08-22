# 0206 — "no rooms" and "could not ask" are different answers

**Date:** 2026-08-22
**Status:** Decided

## Context

`GET /scenes` had been live on api-public since stage 1 and iOS had no client
for it. Three built surfaces were waiting on that one fetch: the returning-home
recent-rooms strip, `RoomsListView`, and `WhySignInSheet`, whose entire
argument is a count it asserts to the user ("You've got N rooms with me
already").

Every one of those surfaces says something to the user about how many rooms
they have. So the question that had to be settled before any of them could be
wired was not how to fetch, but what each of them does when the fetch has not
answered.

## What we tried

The obvious shape, and the one the surfaces were written against, is an array.
`RoomsListView` took `rooms: [RoomSummary]`; `HomeView` takes `hasRooms: Bool`.
Wiring a fetch to those means one of:

- `rooms: (try? await fetch()) ?? []` — a failure becomes an empty list.
- `hasRooms: !rooms.isEmpty` over that same array — a failure becomes the
  first-time hero, the screen that exists for someone who has never scanned
  anything.
- `roomCount: rooms.count` — a failure becomes "You've got 0 rooms with me
  already", inside a sheet arguing that signing in is how you keep them.

All three are one character of Swift (`?? []`) and all three produce the same
sentence: *your rooms are gone*. The third produces it at the exact moment the
app is asking for identity in order to protect them.

## What we chose

`RoomsLoadState` is four-way — `.idle`, `.loading`, `.loaded(rooms:stale:)`,
`.failed(reason:)` — and the accessors that surfaces read are Optional:
`knownRooms: [RoomSummary]?`, `knownCount: Int?`. There is deliberately no
non-optional accessor, because one that returned `[]` for `.failed` would
reintroduce the collapse the type exists to prevent, at the call site instead
of in the store.

Each surface then states its own answer:

- `RoomsListView` takes the state, not an array, and draws all four cases. Its
  failure case says the phone could not ask, does not show an empty list, and
  does not offer the empty state's reassurance.
- Home renders the hero for `.idle`/`.loading`/no rooms — the hero is true for
  everyone, so it is honest to hold the space with — but for `.failed` it
  renders the hero *plus* a line saying the rooms could not be checked. That
  fourth case is `HomeRooms.Presentation.heroWithTrouble` and it exists only
  because falling back to the plain hero is a claim.
- `WhySignInInvitation.shouldPresent` requires a non-nil `knownCount`. A count
  that is merely unknown is not zero, and the sheet has no form that can say
  "some rooms", so it is not offered at all until the next launch.

A refresh that fails *after* a success keeps the rooms it had and marks them
`stale`. Those rooms were really sent; only their currency is in doubt.

## Why

Decision 0216 deleted `AccountConflictView` because one of its two numbers
could not be obtained without performing the act it was asking permission for,
and a number reads as measured. The same standard applies here, and this is the
cheaper and more likely version of it: an unknown count that renders as zero is
not a missing number, it is a wrong one, presented with the same confidence as
a right one.

The asymmetry is what makes it worth a type rather than a convention. Showing
"couldn't check" to a user who genuinely has no rooms costs them one line of
text they can ignore. Showing "0 rooms" to a user who has four tells them their
work is gone, and the surface most likely to do it is the one whose whole
purpose is to promise it is not.

`stale` is a separate axis from the four states for the same reason: it is the
honest name for "this was true when it arrived", and folding it into `.failed`
would blank a list the app has every reason to keep showing.

## What would change this decision

Nothing about the transport. If the app ever gains an offline cache of the room
list — a local mirror written on each successful fetch — then `.failed` with a
cache available becomes a fifth answer ("here is what I last knew, from
disk"), which is `stale` with a longer memory rather than a new kind of claim.
The rule that survives is the one this note is about: a surface may say zero
only when something said zero.
