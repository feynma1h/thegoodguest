# 0361 — the website leaves cream for daylight, slate ink and dusk

**Date:** 2026-11-10
**Status:** Decided — built on `worktree-web-redesign`; not yet deployed to the live site

Supersedes 0122's landing. Amends 0057 on the website (0366 amends it on iOS).
The mark rules of 0248 and the two terracottas of 0249 stand.

## Context

The website still wore 0057's language: cream paper, a warm near-black ink,
Source Serif 4, Instrument Sans and IBM Plex Mono, and bordered cream cards. The
operator judged that it did not look like a professional product, pointed at
worldlabs.ai, and allowed a complete overhaul: anything could go and anything
could be added. The design guides the operator supplied (Impeccable, Hallmark,
Taste) each name "cream with a serif and a clay accent" as the most
generated-looking default.

## What we tried

A first version on a design canvas, which the operator rejected. A second,
which they approved, followed by eleven more screens, then the page-not-found
screen and the share image. Every screen was drawn and approved before it was
built.

## What we chose

- **Colours** (`web/src/app/globals.css`):
  - Daylight ground `#f5f6f8`, white surfaces, parchment `#e4e9ed`.
  - Slate ink `#121a23`. Secondary text is `#4a5664`, and `#808b98` is for
    large text only (3.21:1).
  - Dusk `#0d141c`, `#121b25` and `#1d2834`, with `#eef2f6` and `#a7b2bf` on
    it.
  - Terracotta `#c04d3e` for the mark, `#a54235` for anything text-sized
    (0249), and lamplight `#f0b26a`.
- **Faces:** Newsreader for display type and the guest's italic voice, Albert
  Sans for everything you operate, and JetBrains Mono for measurements only.
  No tracked capitals, and no mono labels.
- **Buttons:** ink pills on daylight, and the same pair reversed on dusk.
  Terracotta never fills a button, except for the one irreversible act the
  site offers: deleting an account.
- **Dusk** is where a room is shown in light. It covers the room page in every
  state (waiting, ready, partly arrived, failed), the phone-to-desk listening
  panel and the footer. Everywhere else is daylight.
- **The landing** is told around a hand-built sample room
  (`components/sampleRoomScene.ts`). That is the second three.js entry point,
  and it never draws a person's room. It uses the product's diorama camera:
  four corner views, with free rotation until one is picked. It replaces
  0122's reveal hero. Night mode is shown, never announced, and the calling
  card stays off the home page.
- **The house** shows each ready room by its measured plan, using the calling
  card's own drawing (`layoutPlan`, `PlanFigure`). Every number on it is a
  measurement, printed to one decimal, and so is the sample room's.
- **The share image** is drawn by the site itself (`/share-card`, inert unless
  `NEXT_PUBLIC_SHARE_CARD=1`). `docs/product/og-card.html` stays only as the
  precedent `measure.test.ts` reproduces.
- **The header** carries the wordmark at its 50px legible floor, in one ink,
  and never beside the mark (0248).

## Why

The operator ruled on the canvas. Cream with a serif and a clay accent reads as
a template. A cool daylight ground with one dusk register leaves the room, which
is the product, as the one warm thing on the page.

## What waits on other lanes

The site claims two things that are true only once other work ships:

- **"Any iPhone works"** becomes true when the iOS build that carries 0364 is
  the one people install.
- **Each piece "modelled from your own photographs"** becomes true when 0360's
  furniture step is live. Under 0360 the privacy page that describes that step
  is not deployed to the live site before it, and this site carries that page.

## What would change this decision

- The operator's eye, again.
- A measured legibility failure.
- A launch that needs the website and the app to look different.
