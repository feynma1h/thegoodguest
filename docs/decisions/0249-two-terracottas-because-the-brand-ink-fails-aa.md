# 0249 — two terracottas, because the brand ink fails AA on text

**Date:** 2026-08-26
**Status:** Decided

## Context

The new palette's brand ink is `#C04D3E` on a `#F9F2EC` cream. The design file
records the pairing at **4.33:1** and does not flag it, because in that document
the terracotta is only ever a mark or a large heading.

The repo uses `--accent` differently. `text-accent` appeared on ten small-text
sites — links in Terms and the legal chrome, `text-xs` status lines in
`SignInPanel` and `DeleteAccountPanel`, `text-sm` labels on `/rooms` and
`/room` — where 4.33:1 is below the 4.5:1 that WCAG AA requires for normal-size
text. The previous rust `#8e3b2f` cleared it, so nothing had ever surfaced.

## What we tried

**Desaturating or lightening the brand ink** so one value serves both jobs. The
charter forbids this without asking, and rightly: the mark's colour is the one
thing in the identity that must not move, because it is what makes the icon, the
tab and the header the same object.

**Leaving it and accepting 4.33:1.** Defensible for a logo. Not for a link.

## What we chose

Two values, same hue and saturation, differing only in lightness:

- `--accent: #c04d3e` — the BRAND ink. The mark, fills, large emphasis. The
  exact value `gen_mark.py` draws with, asserted equal by `test_gen_mark.py`.
- `--accent-deep: #a54235` — text-safe at **5.52:1**. Links, small emphasis,
  hover.

The ten sites moved to `--accent-deep`. Two link pairs that were
`text-accent hover:text-accent-deep` became `text-accent-deep hover:text-ink`,
which is what the design file's own page CSS does with its links.

Two more failures found by the same measurement and fixed the same way: the
filled button in `DeleteAccountPanel` (cream on terracotta at 4.33:1, a 13px
label) now fills with `--accent-deep` at 5.52:1, and the calling card's two
accent text fills — a 20px dimension label and a 22px italic subtitle, neither
"large" by WCAG's definition — use `accentDeep`.

## Why

The two jobs are genuinely different and were only ever conflated because the
old rust happened to satisfy both. A mark is exempt from contrast minimums
because it is not text; a link is not exempt because it is. Splitting the token
is the smallest change that keeps the brand colour exact where it is the brand
and legible where it is prose.

The rule is stated at the top of `globals.css` where someone reaching for a
colour will read it: **do not set body-sized text in `--accent`.** That matters
more than the values, because the next person adding a small terracotta label
will otherwise re-introduce the same failure and no test will catch it — this is
a design-token convention, not something the type system can hold.

Note the direction of the risk. `--accent-deep` was previously only a hover
colour, so widening its job is safe; narrowing `--accent`'s job is what needed
the audit.

## What would change this decision

If the cream ground ever lightens far enough that `#C04D3E` clears 4.5:1 against
it, the two tokens collapse back into one and `--accent-deep` returns to being a
hover shade. That is a real possibility if the page ground is ever taken toward
white; it is not true of `#F9F2EC`.

If WCAG's normal-text threshold is ever met by APCA-style perceptual contrast
instead, re-measure rather than assume — the two models disagree most on
mid-lightness saturated colours, which is exactly what this is.
