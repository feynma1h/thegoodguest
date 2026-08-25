# 0253 — the pinned-action rule was never propagated

**Date:** 2026-08-26
**Status:** Decided

## Context

Decision 0224 established a structural rule after home's scan button truncated
to "Scan a ro…" at accessibility sizes: **content belongs in the scroll area,
only the action is pinned.** Decision 0238 added the corollary that home's
notice slot must render in both variants, so the next caller with something to
say reaches for the slot rather than stacking outside it.

Both notes are written as rules about *this app*, and both were verified by
screenshot on home. Neither asked what the other screens do.

The iOS test policy has carried a standing list of screens never put through an
accessibility screenshot — `RoomsListView`, `WaitingView`, `FailureView`,
`DoorwayView`, `ProfileView` — with the warning that three separate review
passes claimed AX coverage they did not have, and that the two screens which
actually failed were both read as fine before being shot.

## What we tried

`ScreenGallery` (this session) makes every surface photographable from
fixtures, so the standing list could simply be worked through. Thirty-three
screens were captured on an iPhone 17 Pro simulator, twelve of them a second
time at `accessibility-extra-extra-extra-large`.

Measured, at AX5:

- **Home passes.** "Scan a room" is still on screen, wrapping to two lines
  rather than truncating. 0224's fix holds. But the scroll region above it
  collapses to roughly one visible notice — with all three notices present, two
  sit below the fold and nothing indicates they are there.
- **`RoomsListView` loses its action entirely.** The screen ends mid-sentence in
  its footer text; "Scan another room" is below the fold. It is inside
  `RSScrollableScreen`'s scroll region, separated from the rows by a bare
  `Spacer(minLength: 16)`.
- **`FailureView` shows no action on arrival.** A fixed 200 pt art block takes
  the top third, and both buttons are pushed off the bottom. The screen's whole
  stated job is to offer exactly one concrete path, and on arrival it offers
  none.
- **`RoomRow` centres its thumbnail** against a title and status line that each
  wrap to two lines, so the tile comes to rest between them rather than beside
  the title — the same defect the notice components were already top-aligned to
  avoid.

Counted across the app: **two screens pin their primary action** — `HomeView`,
which puts it outside the `ScrollView`, and `GuidanceSheet`, which uses
`safeAreaInset(edge: .bottom)`. Every other screen puts its action inside the
scroll region.

## What we chose

Record the rule's actual reach rather than assume it. 0224 is a rule the repo
believes it follows and in fact applies on one screen out of eleven.

Nothing is fixed here. These are four separate layout changes across four
files, they land in the middle of a live brand lane that is already editing the
shared design system, and the sectioning work they bear on has not been
designed yet. Fixing them now would be fixing screens whose composition is
about to be revisited.

## Why

**A rule verified once on one screen is a fact about that screen.** 0224 and
0238 both read as general — "content scrolls, only the action is pinned" — and
both were true where they were checked. What made them look propagated is that
nobody photographed anywhere else, and the suite cannot see this: all 606 tests
pass with the rooms list's only action off-screen, because they pin routing
logic and the routing is correct.

**The three offenders are not equally bad, and the difference is instructive.**
Home's action is pinned and survives; the cost there is that its *content*
becomes unreachable-looking. The rooms list and the failure screen are
scrollable, so their actions are reachable — but invisible on arrival, which on
a screen whose copy promises "exactly one concrete path" is a different kind of
wrong from a truncated label. 0224's fix was the right fix; it was applied to
the one screen where the failure had been noticed.

**Two of the four are on screens that carry a scan action beside room history**
— which is exactly the surface the current organisation work is about. Any
sectioning of home has to decide where its actions live, and it should decide
knowing that the rule it inherits is honoured in one place.

## What would change this decision

Fix them when the home sectioning lands, since three of the four screens are
candidates for recomposition anyway and the brand lane's palette change touches
the same files. If the sectioning work is deferred, fix `RoomsListView` and
`FailureView` on their own — they are the two where a user is shown no action
at all, and neither fix depends on any design decision that is still open.

Re-photograph after any of it: this note exists because reading was not enough,
and `ScreenGallery` makes the shot cheap.
