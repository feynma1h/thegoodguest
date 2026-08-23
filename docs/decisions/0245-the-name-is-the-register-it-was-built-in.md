# 0245 — the name is the register it was built in

**Date:** 2026-08-23
**Status:** Decided

## Context

The product has had no name. "RoomMind" was discarded in the founding draft;
"roomstudio" has been a stand-in ever since, carried by the repo, the GCP
project, and both wordmarks. Decision 0055 recorded it as a placeholder and the
repo has kept the swap to one file per surface against the day it landed.

That day was forced rather than chosen. Apple Developer enrollment cleared on
2026-08-23, and an App Store listing cannot be created without a name.

## What we chose

**The Good Guest.**

## Why

It is the register the entire product was built in. Decision 0072 named the iOS
design system Good Guest; 0057, 0069 and 0070 built the web on it. The voice
already speaks that way — "Every home holds a version of itself you've never
seen", "Your rooms are where you left them", "Takes about two minutes."

And the metaphor is load-bearing rather than decorative. An AI that enters
someone's home, changes nothing without asking, and leaves something behind IS
a good guest — and the first social increment is literally a **calling card**,
named from this metaphor before the product was.

## What we accepted, knowingly

- **It names the assistant, not the product.** The guest is one of three
  layers. The room, the reveal and the social layer are the others. This is the
  strongest argument against and it was overruled on coherence.
- **"Good" is a claim**, in a voice that conspicuously avoids claims — the
  product says "Takes about two minutes", not "just two minutes". The name is
  the one place the product praises itself.
- **`thegoodguest.com` is taken** by a British company selling indoor sleeping
  bags — "For a Comfortable Stay Away from Home". Physical goods, so a
  different trademark class and negligible legal risk for a product not in
  commerce. But it is the same semantic space, so the name does not own its own
  search results.
- **No App Store app of this name was found**, which is a weak positive. The
  definitive check is App Store Connect and it is now available.

## What is deliberately NOT settled

**The domain still reads `roomstudio.web.app`, and it is printed on the calling
card.** It is the true Firebase hosting URL, so changing the string without
moving hosting would print a falsehood on an artifact that leaves the browser —
strictly worse than an inconsistent one. Settling it means either moving the
hosting site or removing the domain from the card, and both are design calls.

**The repo, the GCP project and the bucket names stay `roomstudio`.** They are
infrastructure, invisible to users, and renaming them is expensive and risky
for no user-visible gain. The stand-in survives where it costs nothing.

**The `roomstudio:`-prefixed localStorage keys stay.** Renaming them orphans
existing state for no visible benefit.

## The re-open trigger

**Commerce.** This name was chosen for a showcase, where coherence with the
design system outweighs owning a search result. If the product is marketed or
sold, the two arguments against — that it names the assistant, and that it
shares its space with another home-goods brand — become real costs rather than
accepted ones.

Renaming stays cheap until App Store submission: TestFlight internal testing
needs only an app record, while the support URL is expensive to change once
filed. **The window closes at submission, not before.**

## What it settles as a side effect

The two lockups have set the name differently — tracked uppercase mono on the
web, the display serif on iOS — and that fork was explicitly parked until the
name landed. A three-word name is too long for tracked mono beside the corner
mark, so the serif wins by construction.
