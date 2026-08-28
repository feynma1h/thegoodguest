# 0257 — one grid for every screen, and an instrument to check it

**Date:** 2026-08-28
**Status:** Decided

## Context

The operator noticed the mark and the first line of content shifting slightly
between screens. Measured, the header ink started anywhere from 73pt to 89pt
down and the first content line from 112pt to 156pt; the one filled button on
each screen sat 77pt, 104pt or 161pt off the bottom depending on which screen
it was.

Nothing was wrong on any screen taken alone. Every number was plausible where
it was written. The defect only existed *between* screens, which is why it had
survived every review that looked at one screen at a time.

## What we tried

Six rounds of fixing what was noticed. Each round found something real, fixed
it, and reported the layout consistent — and each was followed by the operator
finding another screen that had not been touched. The failure was not in any of
the fixes; it was in the method. Spotting misalignments by eye does not
enumerate, so it cannot terminate.

## What we chose

An instrument first, then fixes driven by it.

`tools/ios_screenshot_gallery.py` photographs every screen in the DEBUG gallery;
`tools/ios_layout_audit.py` measures each one's margin, header band, first
content line and filled button, compares them against `RSScreen`'s constants,
and exits non-zero when an enforced screen deviates.

`RSScreen` holds the numbers. `ScreenHeaderFrame` gives every header the same
44pt band whatever it contains. `RSActions` fixes the *shape* of the action
block — extras above, the one filled button, then exactly one closing line in a
fixed-height slot — so the button's distance from the bottom cannot depend on
how many controls a screen has.

## Why

**The fix had to be a component, not a constant.** The causes were all
different: home's mark sits in a 44pt tap target so its ink centres lower than a
32pt header row; the contents put its inset on the screen rather than the
header, stacking with the header's own; profile set its title two points
smaller; three screens each chose their own gap; the recovery screen had no
header at all. No single number addresses that list. A shared component does,
and a screen that does not use it is visible in a diff.

**The instrument is the part that generalises.** It found five screens nobody
had mentioned, and it will find the sixth when someone adds a screen without
composing from `RSScreen`. A check nobody can run is not a check, which is why
both scripts live in `tools/` rather than in a session's scratch directory.

**AND THE INSTRUMENT ITSELF NEEDED FOUR CORRECTIONS**, each of which produced a
confident wrong answer before being caught:

  1. it counted the primary button's 20pt drop shadow as content, so every
     screen with a filled button reported the same wrong margin;
  2. it read the home indicator as the last content row on every screen;
  3. it used each row's own median as the background, so a full-width dark card
     made the light margins either side of it read as ink;
  4. it mixed points with pixels when excluding the button's rows.

Every one of them showed up as the SAME deviation on unrelated screens. **A
uniform result across screens that share no code is the signature of measuring
the instrument rather than the thing** — the first run reported 29 of 29 screens
broken, which is what caught it. That heuristic is the most portable thing in
this note.

## What would change this decision

The audit enforces a band, not an exact number, because ink position inside an
identical box legitimately varies with the glyph: a serif capital, a mono digit
and a drawn mark do not start at the same pixel. If those bands are ever
tightened, the tolerances have to be justified against side bearings rather
than picked.

Screens classified `ceremonial` — the capture overlay, the held beat after a
scan, the doorway, the splash — are deliberately outside the grid. If one of
them is ever brought into the ordinary shape, it should be removed from that
list rather than special-cased inside the audit.
