# 0009 — GFE intercepts /healthz on Cloud Run public URLs

**Date:** 2026-05-24
**Status:** Decided

## Context

After a successful deploy of `perception-obj` (revision 00020-89n), the
`/healthz` endpoint returned a Google Frontend (GFE) HTML 404 when hit
from outside — the standard Google error page with no
`x-cloud-trace-context` header, meaning GFE never forwarded the request
to the container. At the same time, `/readyz` worked correctly and
returned the expected JSON from the container.

The startup probe (configured as `httpGet /healthz`) had passed and the
container was marked healthy. This is because Cloud Run startup probes
hit the container directly over the instance's internal network,
bypassing the public-facing GFE layer entirely. A probe can succeed on
a path that is simultaneously unreachable from the public internet.

## What we tried

**Diagnostic:** Curled `/`, `/healthz`, `/health`, `/ping`, `/readyz`,
and `/ready` against the live service URL. Key results:

| Path      | Response                        | x-cloud-trace-context |
|-----------|--------------------------------|-----------------------|
| `/`       | 200 JSON from container        | ✓ present             |
| `/healthz`| GFE HTML 404                   | ✗ absent              |
| `/health` | FastAPI JSON 404 (not found)   | ✓ present             |
| `/ping`   | FastAPI JSON 404 (not found)   | ✓ present             |
| `/readyz` | FastAPI JSON 503 from container| ✓ present             |
| `/ready`  | FastAPI JSON 404 (not found)   | ✓ present             |

`/healthz` is the only path that GFE intercepts. All other paths —
including `/health` — reach the container.

## What we chose

Rename `/healthz` → `/health` and `/readyz` → `/ready` throughout:
`server.py`, `infra/deploy_perception.sh` (startup probe path), and
`services/perception-obj/tests/test_server_registry.py`.

`/health` and `/ready` are the names Cloud Run's own health check
documentation suggests as examples, which gives mild confidence they
won't be intercepted in the future. The `x-cloud-trace-context`
diagnostic confirmed both reach the container before we committed.

## Why

The startup probe passes on the internal path regardless of GFE
interception, so a deployment appears to succeed. The breakage is silent
— the container is healthy, Cloud Tasks can deliver work, and `/ready`
works for readiness polling. The only symptom is that manual external
verification of `/health` is impossible, which makes debugging harder.
Worth fixing even though it doesn't affect pipeline function.

## What would change this decision

If GFE ever starts intercepting `/health` too (undocumented behavior
is hard to rely on), we'd need to pick another path. The diagnostic
command is:

```bash
curl -si "$SERVICE_URL/<candidate-path>" | grep -E "^(HTTP|x-cloud-trace|content-type)"
```

A path that reaches the container will have `x-cloud-trace-context` in
the response and `content-type: application/json` (FastAPI's 404 format)
rather than `content-type: text/html` (GFE's error page format).

## Note on documentation

Google does not publicly document which paths GFE intercepts on Cloud
Run service URLs. The `/healthz` interception was found empirically.
The Cloud Run health check docs
(https://cloud.google.com/run/docs/configuring/healthchecks) suggest
`/health` as an example probe path without mentioning path restrictions.
