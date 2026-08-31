# 0293 — a passing audit and a green suite both miss the fold

**Date:** 2026-09-01
**Status:** Decided

## Context

This repo has learned the same lesson twice already, one layer at a time.

First: **a green test suite is compatible with a broken screen.** The suite pins
flow logic — routing tables, restore selection, poller visibility — and none of
that is rendering, so a screen whose only exit is clipped off-frame passes
every test. The answer was `ScreenGallery` plus screenshots, and the rule that
AX5 claims are re-verified by photograph and never by reading. Three review
passes had claimed AX coverage they did not have.

Second: **a screenshot is only as good as the eye reading it**, and spotting
misalignment by eye across dozens of frames was not converging. The answer was
`tools/ios_layout_audit.py`, which measures every edge in device points and
exits non-zero when an enforced screen deviates — so "the layout is consistent"
became checkable instead of asserted.

This note is the third layer, and it is the first one where **both instruments
ran, both were correct, and neither could see the defect.**

## What we tried

The deletion screen's `done` state has a variant for when the Sign in with
Apple token could not be revoked. TN3194 requires that the deletion still go
through and that the app then direct the person to revoke access themselves, so
that variant carries an instruction the user must act on: open Settings, tap
your name, Sign in with Apple, stop using it for this app.

It was written as a tail — appended after the closing reassurance, which is
where a caveat naturally goes when you are composing the sentence rather than
looking at the screen.

At the default text size it read correctly. At AX5:

- the instruction began on the eleventh line and ran off the bottom of the
  visible region, behind the pinned action bar;
- `Start again` — the control that dismisses the screen and returns the app to
  a first run — sat fully visible above it.

So the one state whose entire purpose is to deliver that instruction could be
dismissed by someone who never saw it. On the screen where the user has just
irreversibly deleted their account.

**Both instruments passed.**

`DeleteAccountCopyTests` was green, including a test asserting that the
`notRevoked` body contains "Settings" and "Sign in with Apple". That test was
correct and is still there. It pins **presence**, and presence is not
reachability.

`ios_layout_audit.py` read **0 of 8 enforced screens deviating**, at both type
sizes, with every number inside the app's established ranges — margin 27,
header ink 81, first content 152, button 89pt off the bottom. Also correct. The
audit measures the screen's **frame**: the content margin, the top of the
header band, the first content line, and the button's offset, left edge and
width. It does not measure what is inside the scroll region, and it should not:
content scrolling behind an opaque pinned bar is the designed behaviour of
`rsPinnedActions` (0287) and is correct on every other screen in the app.

## What we chose

Move the instruction so it follows the headline rather than trailing the
reassurance, and **pin the ordering in the copy test** —
`test_theAppleInstructionPrecedesTheReassurance` compares the two ranges rather
than asserting either string exists.

Re-photographed at AX5: the instruction now reads from "One thing I could not
finish" through "then Sign in with" without scrolling, which is enough to know
what is being asked and that it continues.

The general rule this sets, for any screen added later:

> When a screen's body contains something the user must **act on**, and the
> screen carries a **pinned control that ends the interaction**, the actionable
> content has to be positioned to survive the accessibility fold — and its
> position must be pinned by a test, because nothing else in the stack can see
> it.

## Why

The instinct on finding this was to reach for a bigger instrument. That is the
wrong lesson, and it is worth saying why.

**Neither instrument was wrong.** The suite tests a pure table, which is exactly
what makes the copy reviewable at all — five states readable side by side
instead of scattered through a SwiftUI body. The audit measures the frame,
which is what made the app's grid checkable after eye-based review had failed.
Widening either to cover this would damage what it is good at: a copy test that
knew about layout would need a rendered view, and an audit that flagged
occluded body content would fire on every correctly-designed screen in the app,
because scrolling behind the bar is the design.

**The gap is real and narrow.** It is content that is present, correctly laid
out, and scrollable — but whose *position within the scroll region* carries
meaning. On almost every screen it does not: the body is prose, and the order
is a reading preference. It matters here for a specific structural reason, and
the reason is what generalises: a pinned control that **ends** the interaction
turns everything below the fold into something the user can skip without
knowing they skipped it. Home's pinned scan button does not have this property,
because not scanning is recoverable. `Start again` on a completed deletion is
the last screen of a one-way door.

**So the cheap, correct answer is ordering plus a test on the ordering**, and
the finding to carry forward is not "build a better audit" but "know which of
your screens has a one-way pinned control, and put the actionable sentence
first on those."

There is a fourth layer implied here that has not been paid for: **the
instruments do not know what a screen is FOR.** A gallery entry states what
state it is photographing (`0270`), not what the person looking at it is
supposed to do. That is why a human still has to look, and why the screenshot
pass keeps finding things — this defect, the transparent action bar, the
truncating button label, the splash with no name under Reduce Motion. Four
finds, four different classes, all invisible to a green suite.

## What would change this decision

An audit that measures **occlusion against intent** would subsume the rule: the
gallery already knows which state it is rendering, so an entry could declare
"this text must be visible without scrolling" and the audit could check the
rendered content height against the visible region. That is buildable and was
not built, because one screen needed it and a test on the ordering costs
nothing.

If a second screen acquires the same shape — a one-way pinned control over body
content the user must act on — build the audit rather than writing the ordering
test a second time. Two instances is where the general instrument starts paying
for itself.
