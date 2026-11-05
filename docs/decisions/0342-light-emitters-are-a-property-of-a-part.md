# 0342 — light emitters are a property of a part

**Date:** 2026-11-05
**Status:** Decided

## Context

Decision 0312 found the night light by a part's name, `lamp-shade`, and left a
generic emitter for later. It also recorded a shade glow of 0.55 while the code
drew 0.65.

## What we chose

A part may say `"emits": true`. At night every emitter gets a point light inside it
(intensity 5) and its own glow (0.55), on its own copy of the material; by day it
is off. Only the first two emitters cast a shadow map (`MAX_SHADOWED_EMITTERS`).
`parseFurniture` reads a part named `lamp-shade` as an emitter, so furniture files
written before the property keep their light; the bedside-lamp example spec and
the flow doc use `emits`. The glow is now 0.55 as settled.

## Why

Any piece can be a lamp without a naming rule; the values stay the ones found by
looking.

## What would change this decision

Emitters needing their own strength or colour: the property would become an object.
