# 0351 — Claude's answers are closed-vocabulary JSON, validated in code

**Date:** 2026-11-05
**Status:** Decided

## Context

A twin is parameters (parts in metres, materials), never pixels. The viewer and the package refuse anything outside their vocabulary. Structured outputs shape the JSON but do not make it correct.

## What we chose

`schemas.py` holds three JSON Schemas (finish hints, furniture spec, critique answer: `done` or a full revised spec) over the closed vocabularies (part kinds from `furniture_models.PART_KINDS`, texture kinds, placement rules floor/wall/on/over). Structured outputs need closed objects, so two free-keyed maps are arrays in the answer (named materials, a texture's `p` numbers) and are folded back by `spec_from_answer`. Every answer is then validated in code: the package's `validate_spec`, at most 60 parts, a texture kind in the vocabulary, a placement target that is another boxed piece, nothing below the floor (5 cm tolerance, the placement rules raise a piece that sits lower), and the model inside its box by at most 10% (true rotated extents, not the package's coarse bound). Hints are validated section by section with the package's `parse_hints`; a bad section is dropped with the reason, not clamped, and the good ones stand. An accepted hint is stamped `source: review`.

## Why

"Dropped, not clamped" keeps a wrong number from looking like a right one. Per-section validation means one out-of-range value in a window hint does not cost the door.

## What would change this decision

If Anthropic's structured outputs gain free-keyed maps, the two array encodings can go.
