# 0360 — Which models may see a room, and what the operator ruled on sending

**Date:** 2026-11-05
**Status:** Decided — the operator ruled on the send limits; zero data retention is a later to-do (punchlist G3-05). Amends 0352 (its limits were "proposed").

## Context

0352 built the rules for what leaves the `scene-finish` service and left them as proposals. Anthropic's API documentation (read 2026-11-05) says conversation content is not retained by default, except for its "Covered Models" (Claude Fable 5.1, Mythos 5.1, Fable 5, Mythos 5), which require 30-day retention and are not available under zero data retention unless Anthropic authorises it. A model chosen by an environment variable could therefore change who keeps a room's pictures without anyone deciding it.

## What we chose

- **The send limits in 0352 are the operator's ruling,** unchanged: wall and floor atlases and door/window patches only, never a camera frame; furniture crops person-masked, at most 6 per request, long side at most 768 px; no identifiers; a frame with no person mask is never used; every image the step derives is deleted when the task ends.
- **Only `claude-sonnet-5-5` and `claude-opus-5-5` may see a room** (`constants.ALLOWED_MODELS`). An environment override naming any other model stops the service at startup (`pinned_model`), and `check_privacy` refuses it again on every request. Adding a model is a decision, not a setting.
- **Sonnet 5.5 is the default for both stages** until a measured A/B on a real scan says otherwise. The first measured run uses Sonnet 5.5 with a deliberately low spend ceiling.
- **The privacy page (§5c, §6, §8) and the labels document (§4f) say so,** in the same commit as this note. The page is not to be deployed to the live site until the pipeline is.
- **Zero data retention is not requested yet.** It is a to-do for the operator (punchlist G3-05), not a claim the page makes.

## Why

The operator accepted the limits and the wording. Pinning the models in code makes the retention assumption true by construction instead of by habit.

## What would change this decision

A real run showing a model outside the list is needed; Anthropic changing which models are covered; the operator arranging zero data retention (then the list could grow to any model eligible under it).
