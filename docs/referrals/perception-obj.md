<!--
docs/referrals/perception-obj.md — Open issues referred to the perception-obj owner.

These items were identified during iOS upload path work and runbook hardening but are
outside the scope of that work. The perception-obj owner should triage and track them.
-->

# Referrals: perception-obj

## P1 — Missing SAM 3D checkpoint blocks `/process` ✓ RESOLVED (2026-05-29)

**Severity:** P1 — was blocking smoke-tool happy-path and duplicate-event modes. RESOLVED.

**Resolution:** SAM 3D checkpoint confirmed present at `/opt/sam3d/checkpoints/hf/pipeline.yaml`
on the production serving revision (`perception-obj-00024-89b`). Verified by a live Phase 7
run on 2026-05-29: SAM 3D loaded in 94.6 s with no `FileNotFoundError`; reconstruction
pipeline reached. The `FileNotFoundError` seen on revisions 00002/00003 was an eager-import
failure before lazy-load was wired up — does not recur on current revisions.

**Note on happy-path smoke outcome:** with P1 resolved, happy-path still does not reach
`ready`. The synthetic fixture carries non-decodable placeholder pixels; reconstruction fails
at "Frame 0 image cannot be opened." This is by design — the fix is an ingest validation gate
that fast-fails non-decodable bundles before they reach the GPU (see board item 1 in CLAUDE.md).
P1 is closed; the smoke contract change is tracked separately.

**Original symptom (historical):** `GET /scenes/by-bundle/{bundle_id}` returned `status=failed`
on revisions 00002/00003. Logs showed:

```
FileNotFoundError: '/opt/sam3d/checkpoints/hf/pipeline.yaml'
```

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

**Partial mitigation note (2026-05-29):** the planned ingest validation gate (board item 1)
will reject non-decodable bundles before they reach Cloud Tasks, reducing one DoS vector
(uploading garbage bundles via the normal `/upload_session` path). However `/segment` and
`/objects` bypass ingest entirely — they accept any image directly. P2 remains OPEN until
those endpoints are authenticated.
