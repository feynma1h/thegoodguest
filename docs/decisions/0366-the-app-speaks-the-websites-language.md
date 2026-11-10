# 0366 — the app speaks the website's language

**Date:** 2026-11-10
**Status:** Decided

Supersedes 0072's locked iOS design. Amends 0057 on iOS only.

## Context

In November the website left cream for daylight, slate ink and dusk, set in
Newsreader, Albert Sans and JetBrains Mono. The app still wore the cream
language 0057 and 0072 gave it, so someone opening on the website a room they
had just scanned met a different product.

## What we tried

The redesign review drew every screen in the website's language beside its
before, and the operator approved it. Two of the questions it raised were ruled
on directly: bundle the faces rather than approximate them in system type, and
no Dark Mode, as designed.

## What we chose

- **The website's three faces, bundled** under the SIL OFL and registered at
  launch in the app and the Live Activity (`RSFontFiles`). Titles in Newsreader
  Light, the guest in Newsreader italic, everything operated in Albert Sans,
  measurements in JetBrains Mono. The navigation bar's titles take the same
  faces (`RSNavigationBar`). The Dynamic Type ceiling and tiers of 0258 stand.
- **Daylight ground `#f5f6f8`, slate ink, dusk `#0d141c`** for the screens that
  are about light and the room: capture and ready. The icon, the splash and the
  launch screen sit on the same ground. Cream and its names are deleted.
- **Terracotta only for the mark, the rings and measurements** — never a fill,
  never a status, never body text. **Lamplight `#f0b26a` only as light, and only
  on dusk**: the tracking dot while tracking is good, and a room moving or ready
  where the Live Activity sits on dark. On the light Lock Screen card it is ink.
- **One filled pill per screen**, ink on daylight and light on dusk; every other
  action is quiet text. Google's sign-in button is drawn to match Apple's size,
  as Google's guidelines ask, with Google's own G read from its SDK.
- **No Dark Mode.** The dusk screens are the dark ones.

## Why

One product, one language: the phone and the website are the same company
speaking, and a room should look like itself on both.

## What would change this decision

A change to the website's language (the app follows it), or measured legibility
trouble with a face at the sizes the app sets it.
