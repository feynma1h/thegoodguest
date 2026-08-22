# 0224 — a pinned action does not share a column

**Date:** 2026-08-22
**Status:** Decided

## Context

Home's failed-rooms-fetch variant is the hero plus a line saying the phone
could not check (decision 0206). The obvious place to put that line is where
`RootFlowView` already puts home's other transient rows — the upload-failure
banner and the re-entry row — which is in the wrapper `VStack` above
`HomeView`, outside `HomeView`'s own `ScrollView`.

It was written that way, and it was wrong in a way that only a screenshot
shows.

## What we tried

Screenshotting home at `accessibility-extra-extra-extra-large` with the trouble
line stacked above `HomeView`.

`HomeView` is `VStack { header; ScrollView { hero }; scanAction }` — the hero
scrolls, and the scan action is pinned to the bottom, which is the whole point
of that structure ("the app never stops being a camera first"). At AX5 the
trouble line wraps to four lines and occupies roughly 370pt. The `VStack` then
has less height to distribute, and the part that gives is the pinned action:
`Label("Scan a room")` truncated to **"Scan a ro…"**, and its support line to
**"Takes about two…"**.

The ScrollView absorbed nothing, because it was not in the squeezed path — it
had already been sized, and the compression landed on its sibling.

Two smaller defects in the same shot, same class: the row's `wifi.exclamationmark`
glyph was vertically centred against four lines of wrapped text and came to rest
in the middle of them, reading as punctuation; and "Try again", placed beside
the message, wrapped into a two-line stub in a column of its own. The rooms-list
header had the third instance — "Your rooms" wrapped to two lines and the back
chevron, centred against the wrapped block, sat between them.

## What we chose

`HomeView` grows a `notice` slot, rendered inside the `ScrollView` above the
hero. The trouble line moved into it. Existing call shapes keep working through
convenience initializers, one per `EmptyView` combination — a defaulted generic
slot cannot be inferred at a call site that omits it, which is why there are
three inits rather than a default value.

The trouble line itself is now top-aligned, and moves its action below the
message once the message needs the full width. The rooms-list title is capped
with `maxSize:` and top-aligned against its chevron.

## Why

The pinned action is the one element on that screen that must survive every
type size: it is the only way forward, and a truncated primary action is the
failure mode the design's scrollable hero was introduced to prevent. Anything
placed in the same fixed column competes with it for height, and at
accessibility sizes there is no height to compete for.

So the rule is structural rather than cosmetic — *content goes in the scroll
area; only the action is pinned* — and it is cheaper to give the view a slot
than to ask every future caller to remember which side of the ScrollView they
are on.

The three defects share a cause worth naming: at AX5, text that was one line
becomes four, and anything aligned to its centre ends up in the middle of a
paragraph. `.center` is the default `HStack` alignment, so this is what a
correct-looking `HStack` does by default. Top-align anything sitting beside
prose that can wrap.

None of this is reachable by reading. The iOS test policy already says AX5
claims must be re-verified by screenshot, and this is the fourth pass to find
by screenshot what three passes read as fine.

## What would change this decision

Nothing about the rule. What is worth acting on separately is that
`UploadFailedBanner` and the home re-entry row are still stacked outside the
ScrollView, in exactly the position that produced this — they are shipped and
were not this lane's to move, and they have not been screenshotted at AX5 with
the pinned action in frame. If one of them is ever found truncating the scan
action, the fix is this slot, not a shorter string.
