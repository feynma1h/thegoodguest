# 0367 — one column, after the website

**Date:** 2026-11-11
**Status:** Decided

Amends 0365 (the grid it retired comes back, as a component) and 0257 (the
grid, again). Implements 0366's No Dark Mode. Adds the one exception to
PROJECT.md's "nothing restacked to fit".

## Context

The layout audit, recalibrated to the redesigned screens, found their titles on
three columns (16 on home and a room, 20 on review, account and deletion, 22 on
guidance) and the pinned button at two heights. Each screen had set its own
insets after a canvas that put text 4pt inside the cards' edge. The website
keeps one edge per container, `px-4` on a phone. The operator asked for those
findings fixed structurally rather than a pixel at a time, for the app to stay
consistent with the website, and for every screen to be right at every text
size, in light and dark, on every device. Then they asked for the frames to be
judged against the design guides rather than by tests written when pixels were
set by hand.

## What we tried

- **Fixing what the audit flagged, one bound at a time.** That is the method
  0257 already found does not converge, so it was not repeated.
- **Fourteen design skill packs**, read and none installed (all install by
  script; none has native iOS guidance). Three were useful as method:
  design.md's one source of truth, ui-ux-pro-max's checklists at every size and
  theme, and break-ui's stress-every-state-before-fixing. That last one found
  two overflows in the shipped redesign: home's first run 15pt wider than a
  375pt phone, and the ready screen with a real 4:3 still wider than every
  phone.
- **A frame-by-frame review** of about 630 frames: 70 states on an iPhone SE,
  17 Pro, 17 Pro Max and iPad Pro 13 at default and AX5, plus extra-small and
  dark. It was read by eye and with the Mac's text reader (Vision) against
  Impeccable, Hallmark, ui-ux-pro-max, break-ui, Taste and the website. It found
  thirteen problems the audit could not see. Eleven were fixed and two left as
  they are (below). Among them: two rooms
  named alike on home, sizes to the centimetre where the website prints one
  decimal, iPad lines of 94 characters, and Bold Text doing nothing. The report
  is `outputs/reports/ios-design-review.md` (gitignored).
- **Rearranging three screens at the accessibility sizes only**, to bring what
  the person needs into view: today's-limit instruction above its steps card,
  the ready screen's Safari line out of its bar, and the account ID under its
  label. The operator accepted the ID and declined the other two. They ruled
  that no screen is rearranged for particular sizes. A cleaner version of each
  was also set aside: the guest's message first on every room screen at every
  size, and a ready picture that shrinks for its words.

## What we chose

- **`RSLayout`, one column.**
  - 16pt in on a phone.
  - On a wider window it stops at 520pt, the website's paragraph measure
    (`max-w-[520px]`), and centres. At 640, an iPad's lines ran to 94
    characters; now the longest is 79.
  - `RSScreenTitle` sets every title in the content. Home's title moved there
    from the navigation bar's large title, which UIKit places on its own margin.
  - `RSPinnedBar` and `RSBarCaption` are the one action bar.
  - `rsHeroFrame` makes a hero picture 340pt, or 58% of what the screen shows.
- **The website's surfaces:**
  - cards at its 24pt corner with its card shadow (`rsCardShadow()`);
  - hero pictures at its 28;
  - room sizes to one decimal (its `formatM`).
- **Every variation the app can be seen in:**
  - `UIUserInterfaceStyle = Light`: 0366 ruled out Dark Mode, but nothing
    implemented it, and the system's alerts turned dark grey over daylight
    screens;
  - Bold Text steps every style a weight heavier (`RSFont.bolder`);
  - a title's last two short words are held together;
  - a label set on a picture is clamped like a control's;
  - the copy button is a 44pt target.
- **The account ID restacks** (operator, 2026-11-11). Wherever the label and
  the whole ID won't fit side by side, the ID goes on its own line under the
  label, as iOS's Settings rows do. It is the only row that changes its layout
  to fit, and it does so by fit, not by text size.
- **The instruments are tripwires** (operator, 2026-11-11). The frames, read
  against the design rules and the website, judge a screen. The audit and the
  density guard catch what is broken by any standard: a cut-off line, content
  off the column, a frame that never drew. The layout rules began as the
  operator's eye (0257), and 0293 already showed a passing audit can miss a
  wrong screen.

## Why

**One product, one language** (0366): the website keeps one edge per
container, so the app does.

**A component, not a number** (0257): the drift existed only between screens,
so only a shared component removes it.

**Reading width follows reading, not the window.**

At the accessibility sizes, the operator wants one layout at every size, just
larger. Data is the exception, because cutting an ID to keep a layout loses the
thing the row is for.

Measured after the changes, on all four devices at default and AX5, and on the
SE at AX5 with Bold Text:
- **Audit:** 4 of 56 enforced states off the column on every pass. They are
  deletion's four that lose their bar (open defects, iOS).
- **Density guard:** 0 of 56 over the ceiling.
- **Text reader:** no cut-off text once the ID restacked.
- **Tests:** iOS 957 executed (6 skipped by design, 0 failures); `tools/`
  128 passed.

## What would change this decision

- **The website changing its gutter or its measure.**
- **A large-title API that can place a large title on a custom margin.**
- **People at the accessibility sizes missing what is below the fold.** On an
  iPhone SE at AX5, today's limit puts the guest's "keep the app open" below
  the fold, and the ready screen's bar covers its size line. Both are read by
  scrolling. Evidence that people miss them would reopen guest-first ordering
  and the shrinking ready picture, at every size, not only the large ones.
