# 0357 — Accepted specs are cached as JSON, and a re-drive needs no pixels

**Date:** 2026-11-05
**Status:** Decided

## What we chose

Each piece writes `work/furniture/<box_id>.json`: status (passed or failed), the best spec, its numbers, the edit history, the calls made, a hash of its box and the stamp that made it. After every accepted edit a `running` checkpoint is written, so a Cloud Tasks retry resumes from the best spec and never re-pays for calls already made; a finished piece is returned from the cache. No pixel, crop or render is ever in these files. `python -m claude_layer.redrive --scene-dir DIR | --bucket B --scene-id ID [--piece box_0 ...]` re-places the cached specs with the current rules and republishes (all pieces, or only the named ones inside the published file). It reads JSON only, so it works after the capture photos are swept (0086). A piece that never passed has no spec to re-drive; that takes a new scan.

## What would change this decision

If a rule change should re-run Claude (not just placement), the cache needs the evidence again, which this design deliberately does not keep.
