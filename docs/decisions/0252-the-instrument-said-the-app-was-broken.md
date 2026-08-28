# 0252 — three more corrections to the layout audit, and the shape they share

**Date:** 2026-08-28
**Status:** Decided

## Context

`tools/ios_layout_audit.py` measures each screenshot's content margin, header
band, first content line and pinned button, and exits non-zero when an enforced
screen deviates. It has needed four corrections already, each of which produced
a confident wrong answer first: it counted the primary button's 20pt drop
shadow as content, the home indicator as the last content row, a full-width
dark card's own fill as the background for the rows it covered, and it mixed
points with pixels. Its first run reported 29 of 29 screens broken.

Expanding the gallery from 36 states to 83 and adding a full accessibility-XXXL
pass put it under conditions it had never seen. It reported 7 of 65 deviating
at the default size and 47 of 65 at AX5.

All 54 were the instrument.

## What we tried

**The seven at default size were all Notes screens carrying exactly one note
card**, each reporting a pinned button 575pt off the bottom and a margin of
zero. Notes has no pinned button at all; the action is a small capsule inside
the card.

The first hypothesis was that the run being found was too short to be a button
and a minimum height would reject it. **Measured, that would have rejected every
real button in the app**: a button's label splits its fill into two runs, so the
run found on home is 27pt tall against a 56pt button, while the run found
inside a note card is 14pt. The two are the same size and the same shape.

The second hypothesis was that the *shape* the run belongs to would separate
them — grow each candidate along a column just inside its own left edge, clear
of the label that broke the run, and a button grows to 56pt where a card grows
to its full height. That worked at the default size and **failed at AX5**: a
card at the default size is 133–154pt, and a real button at AX5 is 98–177pt.
The ranges overlap completely.

**The 47 at AX5 were three separate instrument faults.** Every screen with a
filled button reported margin 0 — the original drop-shadow failure, resurfacing
because the button was no longer being found. Every `contents-*` and every
`desk-*` reported the same "content 153" or "content 155". And several screens
with genuinely centred content reported margins of 46–48.

## What we chose

**The button is identified by three bounds together, each carrying the
measurement that set it.** Over all 166 frames: width 340–350 for a button
against 347–350 for a card and 254 for the capsule inside one; height 53–60 at
default and 98–177 at AX5 against 133–616 for a card; bottom offset 77–186 for
a button against 554–575 at default and 0–70 at AX5 for a card. No single axis
separates them; all three do, on every frame. A fourth bound — a 40pt floor off
the bottom edge — is not about cards at all: `RSActions` sits inside the safe
area, so a pinned action can never touch the bottom edge, and a full-width
shape that does is content running off the screen.

**The background is sampled per row.** One median colour for the whole image
assumes a flat ground and the parchment is a gradient. That survived while the
excluded rows were a band at the *bottom*, leaving one contiguous region whose
median sat in the middle of it; at AX5 the button moves up the screen, the
exclusion punches a hole in the middle, and the median then sits in neither
remaining chunk.

**Two of the five bounds are enforced only at the size they were calibrated
at.** The first content line and the button's offset off the bottom both move
legitimately at AX5, because the header glyph above one and the closing line
below the other are taller. The margin, the header band's top and the button's
own left edge are stated in points and hold at every size. The run prints which
set it applied.

**The margin is loose by nature and says so.** It is measured from ink, and on
a sparse screen the only ink at the left edge is a chevron's single vertex and
an italic serif capital — 40pt on `notes-quiet` with a correct layout. It
catches the defect it is for, a screen that forgot `RSScreen.horizontal` and is
off by a whole 26; the button's own left edge, measured from a container rather
than a glyph, is the exact check. Profile centres its content, where an ink
margin is not a margin, and is classified rather than excused.

## Why

The rule that caught all three was the same one that caught the previous four:
**a uniform result across screens is the signature of measuring the
instrument.** Seven Notes screens deviating identically, and every `desk-*`
reporting the same content offset, are not seven and fifteen bugs.

What is new here is the second half of that rule, which the previous four
corrections did not need: **the obvious fix is measured before it is
believed.** Both hypotheses about the button were plausible, both would have
been shipped by reading the code, and both were wrong in a way that only a
number showed — the first would have silently stopped checking every button in
the app while reporting zero deviations, which is worse than the false alarms
it replaced.

The audit's value depends entirely on a deviation meaning something. It has now
cried wolf seven times and been right zero, so the bar for adding a bound is
that it comes with the frames that set it.

## What would change this decision

If a screen ever ships a full-width filled shape of button height sitting
within 290pt of the bottom that is *not* the pinned action, the three bounds
stop separating and the instrument needs a fourth signal — the strongest
unused one is that a button's label is centred within its shape while a card's
text is left-aligned.

If the app gains a screen whose content is neither left-aligned nor centred,
`CENTRED` stops being a two-way classification.
