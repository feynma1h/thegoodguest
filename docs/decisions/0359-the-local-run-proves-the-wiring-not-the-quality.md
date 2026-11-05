# 0359 — The local run proves the wiring, not the quality

**Date:** 2026-11-05
**Status:** Decided

## What we chose

`python -m claude_layer.local_run SCENE_DIR OUT_DIR` drives `/finish`, every `/furniture-piece` and `/furniture-merge` over the chain on a scene folder, with the fake client replaying the scene's own earlier specs as if they were Claude's answers, the `StubRenderer` (flat silhouettes, an empty region-id pass; marked NOT A RENDER and recorded as `renderer: stub` in every output), boxes derived from the scene's `furniture.json` (it predates `boxes.json`) and person masks assumed empty (`assume_no_people`; the one place that opt-out is used). The scene folder is read only; outputs go to OUT_DIR as JSON.

## Why

It exercises the contracts (frames, masks, task order, caching, single publish, pixel deletion) before any money or cloud is involved. What it cannot show: how Claude behaves, how the real renderer's numbers compare, whether specs from phone-made boxes are good. Those belong to the first real run after review.

## What would change this decision

Track B's renderer landing: the run should then switch to it and the stub should be deleted.
