# 0365 — home is your rooms, and each room has one screen

**Date:** 2026-11-10
**Status:** Decided

Supersedes 0254. Amends 0257 (the grid, not the instrument) and 0302 (the
camera now shows on every scan).

## Context

0254 shaped home as a claim, one routed sentence and a pinned action, with
everything else behind a contents screen. To follow one room a person had to
learn four places — the desk, Notes, What's missing and the house — and their
rooms were a tap away from home rather than on it. 0257 gave those screens one
grid, held in `RSScreen`.

## What we tried

Every screen and every state was photographed and redrawn on one canvas before
anything was built (171 boards, `34s5yipxMgr3bZUBCPiwM1`), and the operator
approved it whole on 2026-11-10. The build was then photographed state by state
at the default size and at the largest text size, and fixed against the canvas.

## What we chose

- **Home is your rooms**: cards, newest first, from `GET /scenes`, with Scan a
  room pinned at the bottom and the account top right. A room on its way is the
  top card, with its three steps. What home shows is one pure table
  (`RoomCards`); an unknown count is never drawn as zero (0206).
- **Each room has one screen** that states everything the desk, Notes and What's
  missing used to split: three steps, the guest's line, at most two actions. One
  pure table (`RoomStatusCopy`) gives every state its words.
- **Ready is a dusk screen** with the room's picture: scene-finish's still when
  the API carries one (0363), the measured floor outline until then.
- **Account is one sheet**: sign-in, the account ID, the privacy policy, delete
  everything.
- **Review takes in "I've got the room"**, and **capture shows the camera on
  every scan, in every build**, with the floor plan as a small card on LiDAR
  phones.
- **The splash still hands the mark over** (0255). Home's mark lives in the
  navigation bar, whose items are hosted apart from the screen, so an anchor set
  there never reaches the splash's overlay; the bar mark reports its frame
  instead (`MarkSlotReport`).
- **`RSScreen`'s grid is retired** with the screens it measured. The audit that
  checked it (0257) stands, and is being recalibrated to the new screens.

The honesty rules carry over unchanged: no ETA and no invented elapsed time, an
unknown count is never a zero, a scan is never called safe above the button that
frees it, and on a screen whose pinned control ends the interaction the sentence
to act on comes first, with a test (0293). Two were found while building: a
scan held by the daily limit is kept only while the app is open, and says so
first; and letting a scan go asks before deleting it, as stopping a scan and
discarding at review already did.

## Why

People expect an iPhone app to show them their things and let them open one.
One screen per room means one place to look, and one table to read and test.

## What would change this decision

Enough rooms that a list stops working (search, grouping), or a second kind of
thing that belongs on home.
