# 0106 — perception-obj is publicly invokable, and stays that way for now

**Date:** 2026-08-09
**Status:** Spent — the platform is the gate as of 2026-08-10 (see Outcome)

## Context

Found during the four-surface deploy, while reading `deploy_api_internal.sh`'s
IAM output: the printed policy for **perception-obj** carries `allUsers` on
`roles/run.invoker`. That is the GPU service which parses untrusted user
bundles — the one decision 0090 went to some length to give a least-privilege
runtime SA. It is worth knowing exactly what that binding does and does not
expose before anyone either panics about it or leaves it unexamined.

It is pre-existing and deliberate, not something the deploy introduced:
`infra/deploy_perception.sh:204` passes `--allow-unauthenticated`, so every
`obj` deploy re-asserts it. It is also asymmetric with api-internal, which is
`--no-allow-unauthenticated` and platform-gated per decision 0016.

## What we tried

Measured the actual exposure rather than reasoning from the binding:

- `POST /process` and `POST /shell` with an empty body, no token → **422**.
  That is FastAPI/Pydantic rejecting the body before the handler is entered,
  so a malformed request never reaches an auth decision — and never reaches
  any work either.
- Read the ordering rather than inferring it: `handle_process` in
  `process_receiver.py:1595` runs OIDC verification as **step 1**, before the
  lease claim, before the repo is stashed, before anything touches GCS or a
  model. A failure returns 401 immediately.
- `POST /process` with a *well-formed* body and no token → **401 in 0.58 s**
  once the container was warm. Auth precedes work, confirmed live rather than
  by reading.
- The same request issued against a cold service **hung past 120 s** — the L4
  container booted in order to return the 401.

So the posture is: the platform is open, and the application is the gate. That
is the same shape as api-public (deliberately `--allow-unauthenticated`, with
in-app Firebase verification), not a hole.

## What we chose

Leave it. Record it, with the measurements, and hand it to the IAM-audit
thread that decision 0088 opened.

## Why

Changing it during a deploy would be the wrong move twice over. It is not a
one-flag change in effect: flipping to `--no-allow-unauthenticated` makes the
platform the gate for the Cloud Tasks delivery path as well, and while
`tasks-invoker@` already holds `run.invoker` (so it would very likely keep
working), "very likely" is not a thing to find out during a four-surface flip
with no capture in flight to test against. The blast radius of being wrong is
the entire perception pipeline going silently undeliverable.

And the residual risk is genuinely small but genuinely non-zero, which is why
it wants recording rather than either action or silence. No unauthenticated
caller can make this service do work — 401 lands before the lease claim. What
an unauthenticated caller *can* do is **cause an L4 GPU container to boot**,
which is a cost vector rather than a data one, bounded by `max-instances=1`.
That is the whole of it, and it is the part that would be invisible to anyone
reading only the IAM binding or only the handler.

Two smaller things fell out of the same policy dump, both cosmetic:
`tasks-invoker@`'s `serviceAccountUser` binding still lists
`deleted:serviceAccount:api-runtime@…` as a tombstone member — the SA was
deleted in the ship-ops session (0103) but the binding was not swept — and the
same is worth checking for wherever else that SA appeared.

## What would change this decision

- Any evidence of unauthenticated traffic actually reaching `/process` in
  production (a 401 rate above background noise in the logs) turns the cost
  vector into a live abuse problem and forces the flip.
- The first non-developer user at scale: `max-instances=1` is what currently
  bounds the exposure, so raising it raises this with it.
- ~~If the IAM audit from 0088 is picked up as its own pass, this belongs in
  it~~ **FIRED — see Outcome.** The right
  test at that point is whether Cloud Tasks delivery survives
  `--no-allow-unauthenticated`, exercised against a real capture rather than
  a synthetic one.

## Outcome — flipped 2026-08-10, verified live in both directions

The audit pass this note's third trigger asked for ran as its own ops
session, and the flip is done. `roles/run.invoker` on perception-obj now
holds exactly `serviceAccount:tasks-invoker@roomstudio.iam.gserviceaccount.com`
(it already held it beside `allUsers`, as this note predicted, so the flip
was one grant-assert and one removal); `infra/deploy_perception.sh` deploys
the obj path `--no-allow-unauthenticated` and asserts the invoker grant
post-deploy, so neither half regresses on the next deploy. The geom path is
untouched (parked, no Cloud Tasks caller).

Measured, not assumed:

- **Negative:** unauthenticated `GET /health` and `POST /process` return the
  Cloud Run **frontend's HTML 403** in ~0.7 s — the platform gate, not the
  app's JSON 401/422 — so an unauthenticated probe can no longer boot the L4.
  The cost vector this note measured is closed. (During the ~3–4 min of IAM
  propagation after the removal, unauthenticated requests still reached the
  app and one booted a cold container in 12.3 s — the 0088 lesson about
  reading propagation lag as a failed revocation, re-observed.)
- **Positive:** `tools/reenqueue_scene.py a7e073ae-… --shell` on the ready
  spike scene — real Cloud Tasks, real OIDC as `tasks-invoker@` — landed
  **200 in 1.75 s** one second after enqueue, with the app's own
  `shell: scene … already has shell.json v3; noop` line and the queue
  drained with zero retries. Delivery survives the flip.
- **Operator access:** a project-owner identity token still invokes (200
  post-propagation), so candidate `/health` checks now need
  `-H "Authorization: Bearer $(gcloud auth print-identity-token)"` — noted
  in RUNBOOK Phase 0h, whose unauthenticated `/ready` curl now reads 403 and
  still passes its own "any HTTP response proves reachability" gate.

App-side OIDC verification stays exactly as it was — the platform gate is in
FRONT of it, defence-in-depth rather than replacement.

Both cosmetic findings from the original policy dump are also swept: the
`deleted:serviceAccount:api-runtime@…?uid=108635943216748568773` tombstone is
removed from `tasks-invoker@`'s `serviceAccountUser` binding (the live
members are default-compute, `api-internal-runtime@`,
`perception-obj-runtime@`). The default-compute member of that binding looks
like a pre-0090 leftover (perception-obj enqueued as the default SA then) —
left for the default-compute verification pass 0090 already names, not swept
here.
