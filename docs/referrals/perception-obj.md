<!--
docs/referrals/perception-obj.md — Open issues referred to the perception-obj owner.

These items were identified during iOS upload path work and runbook hardening but are
outside the scope of that work. The perception-obj owner should triage and track them.
-->

# Referrals: perception-obj

## P1 — Missing SAM 3D checkpoint blocks `/process` (BLOCKING)

**Severity:** P1 — blocks smoke-tool happy-path and duplicate-event modes; blocks Phase 8c (iOS code start).

**Symptom:** `GET /scenes/by-bundle/{bundle_id}` returns `status=failed` after a happy-path
upload. `perception-obj` logs show:

```
FileNotFoundError: '/opt/sam3d/checkpoints/hf/pipeline.yaml'
```

**Root cause:** `SAM3DModel.__init__` attempts to load the SAM 3D Objects pipeline config
from `/opt/sam3d/checkpoints/hf/pipeline.yaml`. The file is absent from the deployed image.
The error fires on the first `/process` call (model load is lazy per decision 0007); the
container starts and passes `/health` before the load is triggered, so Cloud Run marks the
revision `Ready True` with no visible startup failure.

**Current state:**
- `skip-blob` and `auth-rejection` smoke modes pass (neither triggers `/process`).
- `happy-path` and `duplicate-event` modes fail: scene reaches `failed` state instead of `ready`.
- Phase 8c (iOS code start) is blocked until this is resolved.

**Fix:** Ensure the SAM 3D Objects checkpoint file is present at the expected path in the
deployed image. Verify by running `perception-obj /ready` after a `/process` call — it should
return HTTP 200 with `{"sam3": "loaded", "sam3d": "loaded"}` once the fix is deployed.
Cross-reference decision 0008 (bake all model weights at build time) for the Dockerfile
convention: add a `RUN` step that asserts the file exists at the cache path and fails the
build if it is missing.

---

## P2 — `/segment` and `/objects` are unauthenticated GPU-triggering endpoints (SECURITY)

**Severity:** Pre-launch security gap. Theoretical under current state (no users, URL not
advertised) — must close before the same launch gate as the 0015/0018 abuse-surface set.

**Symptom:** `POST /segment` and `POST /objects` accept any image upload with no
authentication of any kind. Both call `get_sam3()` and/or `get_sam3d()`, which trigger the
full ~195s GPU cold-start model load on a cold container.

**Threat:** Under `--max-instances=1` and `--min-instances=0` (scale-to-zero), an
unauthenticated caller can:
- Force a cold GPU VM acquisition + ~195s model load on every cold start.
- Hold the single permitted instance busy with a long-running `/objects` inference job,
  blocking all legitimate `/process` work from Cloud Tasks for the duration.
- Sustain this indefinitely at negligible cost to the attacker (one HTTPS request per cycle).

The GCS output cache in `/objects` (keyed by image SHA-256) provides no protection: a novel
image on each request bypasses it entirely.

**Fix:** Add route-level authentication to `/segment` and `/objects`. Options in rough order
of implementation cost:
1. **Require Cloud Run IAM** (`--no-allow-unauthenticated`) and grant `roles/run.invoker`
   only to the services that legitimately call these endpoints. Breaking change for any
   existing callers of the photo-upload path.
2. **Require a shared API secret** in a header — lower ops cost than IAM, weaker protection.
3. **Rate-limit by IP** at the Cloud Run / Cloud Armor layer.

Note: `/process` is already protected — it requires a valid OIDC token from the Cloud Tasks
invoker SA. The gap is only `/segment` and `/objects`.

Cross-reference: the pre-launch abuse-surface gap set in decisions 0015 and 0018 covers
api-public; this is a separate gap on perception-obj.
