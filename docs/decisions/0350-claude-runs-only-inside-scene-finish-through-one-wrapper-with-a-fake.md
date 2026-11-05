# 0350 — Claude runs only inside scene-finish, through one wrapper that has a fake

**Date:** 2026-11-05
**Status:** Decided

## Context

Phase 2 makes Claude part of every scan: it writes wall hints and one furniture model per boxed object, and each answer is checked against the scan's own photos. That is up to ~90 calls per scan, each of which can carry a picture of someone's home. The tests, the local run and review must never reach the real API.

## What we tried

Calling the SDK from the passes (as `shell_material.py` does for one 256-token call). That scatters spend checks, privacy checks and logging over every call site, and makes a fake client a patch of the SDK.

## What we chose

`services/scene-finish/claude_layer/client.py`: `ClaudeCaller.ask(request, validate)` is the only way a request leaves the service. It checks the images (0352), checks the spend ceiling (0353), sends through a `ClaudeClient`, records the usage the API reports, logs one line of sizes and no pixels (0358), validates the answer in code and re-asks once with the validation error appended. A refusal is never retried. `AnthropicClient` is the real SDK (structured outputs via `output_config.format`, the vocabulary system prompt as the cache breakpoint, adaptive thinking at `FINISH_EFFORT`; no `thinking: disabled` and no forced `tool_choice`, which the 5.5 models refuse). `FakeClient` replays scripted answers and keeps only the SHAPE of each call (counts, sizes, a text hash). Models come from `FINISH_HINT_MODEL` (default Sonnet 5.5) and `FURNITURE_SPEC_MODEL` (default Opus 5.5), and every output file records them.

## Why

One choke point is the only place a privacy or budget rule can be enforced rather than hoped for. The key is the SDK's environment variable; nothing in this code reads, prints or stores it.

## What would change this decision

An eval on real scenes that shows Sonnet matches Opus for the spec write (halving the cost), or a second consumer of Claude in the service that needs a different retry policy.
