# 0287 — the gallery photographs every state, not every screen

**Date:** 2026-08-28
**Status:** Decided

## Context

`ScreenGallery` was built so the iOS test policy's screenshot half could
actually be run: a green suite pins routing tables and pure functions and says
nothing about whether a screen's only exit is clipped off the bottom, so every
layout claim needs a photograph.

It catalogued 36 entries for 36 surfaces. That reads as complete and is not.
Most of those surfaces switch on an enum, and several of those enum cases carry
values that change what is drawn — so a screen with one entry was photographed
in one of the states it can reach and in none of the others.

Counted properly, the 36 entries covered a state space of 83. The desk's six
cases are fifteen reachable renderings once `working`'s anchor and long-running
flags, `rateLimited`'s five copy branches and `checkFailed`'s `stopped` are
enumerated; six appeared. Notes' four kinds and three count clauses are eleven;
three appeared. `FailureCopy.Resend` is four states each changing both buttons
and the body; two appeared. The doorway's `canOpenWeb × signedIntoWeb` is four
screens with four different captions; one appeared.

## What we tried

Expanding the catalogue to the enumerable state space and photographing all of
it at both the default text size and accessibility XXXL — 166 frames.

Three things the expansion needed, each of which was a defect in the harness
rather than a preference:

**A moment, not a settle.** The entry carried a `settles` flag meaning "wait
2.6 s instead of 1.5". Several screens play a timeline where the frame worth
having is at a point in it, and a flag cannot name a point. Measured, home's
menu peek is out from about 2.0 s and gone by 5.2 s — so the old 1.5 s wait
photographed all six home screens on the peek's rising edge, a transient nobody
had noticed was in the shot. The splash has two beats worth keeping and one
wait can only have one of them. Each entry names its own `delay`.

**One clock.** Every fixture derived its dates from `Date()`. The desk's
rate-limit line therefore read "later today" or "tomorrow" depending on the
hour the capture pass happened to run, and the house's stamps changed between a
clock time and a date at midnight. A re-shoot is now the same pixels.

**A status the guidance sheet can be given.** Its denied branch could not be
photographed at all: `xcrun simctl privacy` has no `camera` service, so a
simulator cannot be put into the state a person reaches by tapping Don't Allow.

## What we chose

One entry is one state. Every case of every enum a screen switches on, and
every combination of the values those cases carry that changes what is drawn.
Where an associated value does *not* change the drawing it gets a note instead
of an entry — which is how `checkFailed`'s `anchor` is recorded, having turned
out to be rendered nowhere.

The guidance sheet reads camera authorization through a closure seam, the shape
`public_server._mint_uri_fn` and `UploadSessionRepository` already use here.
Production asks AVFoundation and nothing else does. A closure and not a stored
status, because the sheet asks twice — once as it appears and again whenever
the app returns to the foreground — and the two answers must be able to differ,
or granting access in Settings would never clear the denial.

## Why

The states nobody photographs are where the defects are, and this pass proved
it twice on screens that were already in the catalogue:

**The pinned action bar was transparent.** Five screens pin their action with
`safeAreaInset`, which reserves space and lets content scroll *behind* what
sits there. With no background, at AX5 profile drew "Signing out lives on the
web" letter-on-letter over "to keep them safe across devices", and the recovery
screen and QR bridge did the same. Neither sentence was readable. Only the
guidance sheet escaped, because it happened to set a background of its own.
Nothing about this is visible at the default text size, and 620 tests were
green throughout.

**A filled button's label truncated under pressure.** Review's dormant
thin-coverage branch is the one arrangement with a quiet button above the
primary; at AX5 it squeezed "Scan again from scratch" to "Scan again fr…",
naming no action at all. The same label wraps correctly in every other
arrangement, so nothing about the label was the problem.

Both fixes are structural rather than per-screen — `rsPinnedActions` and the
button styles — because the transparent-bar bug is precisely what per-screen
memory produces: one of five screens remembered.

The scoping rule has a second edge worth keeping. A state that can only be
reached by hand-assembling a lookalike is not a state the app has; the gallery
composes each screen the way `RootFlowView` composes it, so a photograph is of
the shipping layout. Where that could not be done honestly — the denied camera
— the answer was a seam in the screen's own logic, not a second rendering path.

## What would change this decision

If a screen grows a state space that is no longer enumerable — a free-text
field, a list of arbitrary length, a continuous value that changes the layout —
the catalogue stops being able to claim coverage and has to say which states it
sampled and why those. Nothing today is in that shape: every axis is an enum, a
Bool, an Optional, or a count with three named branches.

If `simctl` ever gains a `camera` privacy service, the guidance sheet's seam
can be replaced by driving the real device state, which would be strictly
better evidence.
