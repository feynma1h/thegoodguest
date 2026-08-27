# 0254 — home is a claim, a sentence, and an action

**Date:** 2026-08-28
**Status:** Decided

## Context

Home was calm until it had something to report. Then up to three notices —
the upload-failed banner, the re-entry row, the rooms-trouble line — stacked in
the one column the no-tabs rule allowed, and the product's own claim slid down
the page by however much the day happened to weigh. Worse, the claim vanished
outright after the first scan: the rooms strip replaced it, permanently, with
nowhere to find it again.

Decision 0224 had already fixed the sharp edge (a notice outside the ScrollView
squeezed the pinned action until "Scan a room" truncated). The slot it
introduced was the right fix for the wrong shape: notices still stacked, and
nothing capped how far the claim could be pushed.

## What we tried

Three structural proposals came back from a design pass. The first kept one
screen and moved state onto each room's row; the second split the archive onto
a second screen; the third made the room's own floor plan the hero. All three
left home as the place everything is reported, which is what the operator
actually objected to. The instruction that followed was explicit: **reporting
LESS on home is the ask, not reporting it better.**

## What we chose

Home holds three things. The claim, one sentence, and the pinned action.

The sentence is the whole of home's reporting surface. It routes by priority —
needs-you, arrival, in flight, then a standing fact — and tapping it lands on
the screen where that news actually is. It cannot stack: `HomeLineResolver`
returns exactly one, or none.

Everything home used to report moved to a screen of its own. **The house** holds
the rooms that landed and the thesis at its permanent address. **The desk** holds
the room in flight, which finally gives paused and rate-limited a surface.
**Notes** holds the finished failures waiting to be acknowledged. All three are
reached from a **contents** screen behind the mark — a table of contents rather
than a tab bar.

`RoomsListView`, the recent-rooms strip, the re-entry row and the upload-failed
banner were deleted rather than left unreachable.

## Why

**The claim's position is now fixed whatever the day looks like.** That is the
property the notice slot could never provide, and it is the whole point: a
sentence cannot stack, so nothing can push the claim anywhere. It is on screen
on day one and on day four hundred.

**A contents page can say something a tab bar cannot.** A tab bar states four
destinations permanently, in the chrome, on every screen — the dashboard this
product spent its whole design avoiding. The contents states the same four only
when asked, and tells you on the way past that two things need you. Then it gets
out of the way.

**The split is by what a state IS, not by when it happens** (`SurfacePlacement`).
A room still on its way goes to the desk; a room that has finished failing
becomes a note. The one judgement in it is the send failure, which splits on
whether retrying can work: retryable means the capture is intact and the room
still has a future, so filing it under Notes would ask someone to acknowledge
something that has not finished happening.

**Deleting the replaced screens is decision 0237's rule applied to ourselves.**
Four lanes once edited a screen no build could reach. Leaving five more
unreachable surfaces would have recreated exactly that.

## What would change this decision

If the sentence turns out to be too small a channel — if users routinely miss
news because one line is not enough — the answer is not to add a second line. It
is that the priority order is wrong, or that something in it deserves a surface
of its own the way arrival got the doorway.

`WaitingView` is still in the tree and unreachable, kept as the reference the
desk is being judged against. It should be deleted once the desk is accepted;
the same rule that removed the other four applies to it.
