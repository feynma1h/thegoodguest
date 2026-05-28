# 0024 — Phase 0h gates liveness, not readiness

**Date:** 2026-05-29
**Status:** Accepted

## Context

v2 PR finding #4 named a contradiction: Phase 0h of `infra/RUNBOOK.md` treats `curl ${PERCEPTION_URL}/ready` as a readiness gate, but `/ready` is designed as an observability endpoint (decision 0007). Finding #18 named a symptom: Phase 0h didn't catch perception-obj's missing-checkpoint state.

Cluster D attempted to close #18 by gating Phase 0h with a tri-state branch on `/ready` (200→proceed, 503→bounded retry, 500→halt). On measurement, the gate was wrong: perception-obj lazy-loads on first `/process` (decision 0007), so a cold container returns 503 `not_loaded` *by design* — indistinguishable from broken. The retry loop would fail every healthy scale-to-zero cold deploy. That portion of the Cluster D commit is reverted by this decision; #7 and #8 stand.

This decision resolves #4 and #18 together by reframing what Phase 0h proves.

## What we tried

Considered four architectures for proving perception readiness at preflight.

**Eager-load behind a real Cloud Run startup probe.** perception-obj preloads at startup; broken checkpoints fail at the probe. Under scale-to-zero, every cold start pays ~195s before serving; relocates cost from "first request" to "startup probe," same wall clock.

**Warm-on-upload from api-public at `/upload_session` time.** Fire a fire-and-forget warm-up at the earliest signal a capture is coming, overlapping load with pixel upload. Code's measurements: cold-start + load ~225–285s; realistic upload ~6–70s on mobile upstream. Narrows the gap (~20–70s saved) but cannot close it.

**Min-instances ≥ 1 on the perception tier.** Trivially solves cold-start. Off the table: scale-to-zero is a hard financial constraint.

**Predictive warming during high-traffic windows.** Requires usage data that doesn't exist for a product with no users. Filed for later.

The reframe arrived from the product side: scene completion is delivered via push notification (FCM, per 0014). Capture is asynchronous-by-design and will remain so for at least the next year. Under push delivery, the user has no continuous sense of elapsed time between tap-done and notification-received. A 90-second warm path and a 4-minute cold path are not distinguishable in the user's experience. Three of the four options were optimizing latency that isn't user-felt.

## What we chose

Phase 0h gates liveness only:

1. `gcloud run services describe perception-obj` returns `Ready True`. Halt on anything else. Catches container-failed-to-start (e.g., the protobuf VersionError class from 0021).
2. `curl ${PERCEPTION_URL}/ready` returns any HTTP response — 200 `loaded`, 503 `not_loaded`, 503 `loading`, 500 `failed` all confirm invokability. Halt only on connection failure or platform-level unreachability.

Phase 0h does *not* wait for models to load, does *not* treat 503 `not_loaded` as failure (it's the designed cold state), and does *not* treat cached 500 `failed` as a deploy blocker (next cold container will retry on first `/process`). A cached 500 surfaces as an operator warning, not a halt.

The broken-checkpoint case is caught downstream: Phase 7 happy-path triggers a real `/process`, which triggers a real load, which surfaces a missing checkpoint as a concrete failure routed through the container-failed-to-start branch in the decision tree (Cluster D, finding #7) — that branch names FileNotFoundError on a checkpoint as a known signature.

## Why

What Phase 0h *can* honestly assert is what it *should* assert. `/ready` on a scale-to-zero lazy-load service cannot distinguish healthy-cold from broken at preflight. Gating on a signal identical in healthy and broken states produces false reds, not true detection.

Perception readiness is correctly a runtime concern under push-notification delivery. The user's experience contract is "tap done, get a notification when ready," enforced by reliably reaching a terminal scene state and pushing FCM — not by serving any request within any latency bound.

The broken-checkpoint catch is real, just downstream of preflight, because preflight cannot honestly perform it on a scale-to-zero service.

## What would change this decision

- **Product moves away from push-notification delivery toward foreground UX.** Cold-start latency becomes user-felt; warm-on-upload returns to the menu; perception cold-start time becomes a product-critical metric. Phase 0h might gain a warm-path smoke. This is the trigger that flips the whole framing.
- **perception-obj ships eager-load behind an honest Cloud Run startup probe.** Phase 0h could optionally gain a warm-path smoke at deploy time. Doesn't require this decision to change.
- **perception-obj gains a `/warmup` endpoint.** Unlocks calling `/warmup` from the runbook to surface broken-checkpoint failures at deploy time rather than Phase 7. Phase 0h could then tighten to halt on failed warm-up.
- **Usage patterns emerge supporting predictive warming.** Doesn't change this decision; adds a separate decision about warming policy.
