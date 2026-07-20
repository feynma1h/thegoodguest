# 0057 — Good Guest design language: warm hospitality supersedes 0056's visual specifics

**Date:** 2026-07-20
**Status:** Decided (supersedes 0056's design-language section; 0056's 3D-stack
gating and conversation sequencing stand)

## Context

0056 codified "Apple premium, not gold premium" as neutral achromatic dark
chrome, after a warm-luxury pass (Fraunces + amber) was rejected. A
comprehensive design file then arrived as the new visual authority: **"Good
Guest — Product System"** (`Good Guest - Product System.dc.html`, untracked at
repo root as of this writing) — the product personified as a guest in your
home: warm, permission-spoken, literary; the room page framed as "a
conversation happening in a room; everything else is furniture the
conversation can summon." The founder directed implementing the file as
designed, with every conflict against 0056 recorded rather than silently
resolved, and confirmed the scope calls in-session (disabled composer,
declared-placeholder QR, data-honest demo caption).

## What we chose

Implement the file as the visual authority. Six 0056 clauses are superseded:

1. **Dark-first neutral → warm light-first.** Parchment/cream surfaces
   (`#f7efdf` / `#e9e2d2`), warm-brown ink (`#3a2d22`). Dark warm ink becomes
   the *emphasis register* (reveal threshold, terminal failure) instead of the
   default. Tokens live in `web/src/app/globals.css`.
2. **No brand color in chrome → rust as the action color.** `#8e3b2f` fills
   primary pills and marks emphasis (links, failure tones). 0056 had reserved
   chrome for achromatics with white pills.
3. **Serif retired → serif returns as the guest's voice.** Source Serif 4
   italic is reserved for lines spoken in the guest's first person, plus
   display statements (`GuestLine` in `web/src/components/ui/voice.tsx`).
   Semantic, not decorative: serif = speech, sans = UI. This is 0055's
   "serif = feeling" rule returned with a narrower charter.
4. **Mono never-decorative → mono eyebrows return.** Uppercase-tracked IBM
   Plex Mono section labels (`Eyebrow`); mono keeps machine data (ids,
   coordinates). The wordmark itself renders in eyebrow style with a `❖`
   glyph — the design file's own explicit-placeholder treatment, apt while no
   name exists.
5. **Fonts:** Geist → Instrument Sans; DM Mono → IBM Plex Mono. All via
   next/font (build-time self-hosting; the firebase.json CSP needed no
   change).
6. **De-boxing → boxed warmth.** Bordered cream cards and floating translucent
   overlays are the organizing device, including over the 3D stage.

**The gold line holds.** Muted gold `#c9a25e` enters under a strict charter:
light-semantic indicators only — the capture-time dot, the bridge's listening
pulse, in-flight status dots. Never on chrome surfaces, CTAs, borders, or
text. This is the enforceable form of "not gold premium": warmth as
hospitality passes the founder's bar; gilt as status does not.

**Unchanged from 0056:** the single spring in
`web/src/components/ui/spring.tsx`; SplatViewer/0053 containment (the §4
reveal choreography went *inside* the component — new `frameless`/`reveal`
props; the `PositionedSplat` contract is untouched); R3F still gated at the
reactive-scene boundary; conversation staging; status as quiet signal; and the
no-fake-UI rule, which outranked design fidelity wherever the file drew
unbuilt features — the composer ships disabled and says the guest hasn't
arrived, the bridge QR declares itself unwired, guest lines are template
narration grounded in real counts/status (never fabricated insight), and §6
keeps / §7 directions / §10 sharing + consent register / §11 ambient / the
sun-arc dial were not built at all (the "as captured" chip shows the real
capture time only).

## Why

The emotional layer needs a voice, and neutral chrome had nowhere to put one.
The guest persona gives every state — waiting, failure, the reveal — a speaker
whose warmth serves the thesis (your home, understood by someone who cares
about it) rather than competing with the room; notably, the file's §4
"degraded" objects-before-walls reveal is literally this product's truth
(scene-shell pipeline unbuilt), so the design's honesty and the system's
reality meet exactly there. The founder's standing rule was always about
ornament-as-status, not warmth.

## What would change this decision

- A chosen name with its own brand color re-opens the accent question (rust is
  a placeholder-era choice, like the wordmark).
- If the guest persona is ever retired from product copy, the serif-voice
  charter goes with it — serif without a speaker is decoration, which 0056
  rightly banned.
- Stage-1 conversation shipping replaces the disabled composer and template
  guest lines with the real thing; the layout already reserves their places.
