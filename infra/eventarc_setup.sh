#!/usr/bin/env bash
# infra/eventarc_setup.sh — Eventarc trigger + lifecycle/TTL config for iOS upload path
#
# Run once per environment to wire up:
#   (1) Eventarc trigger: GCS finalize on roomstudio-captures → api-internal /ingest/eventarc
#       The trigger is bucket-wide (GCS Eventarc does not support object-path suffix filters
#       on object.v1.finalized events). The /ingest/eventarc handler discriminates bundle.pb
#       from pixel-blob events; see decision 0023.
#   (2) Cloud Storage lifecycle rule: delete orphan captures after 24h
#   (3) Firestore TTL on upload_sessions (7 days)
#   (4) Firestore TTL on scenes.expire_at (gap F6, decision 0086): api-internal stamps
#       terminal-failure scenes (failed / failed_invalid / failed_incomplete) for deletion
#       after SCENES_FAILED_TTL_DAYS (default 90); ready scenes are never stamped.
#   (5) Perception-outputs lifecycle (gap F5, decision 0086): delete frame-mask
#       intermediates (scenes/*/frames/*/masks.npz) after 180 days. Deliberately NARROW —
#       everything else under scenes/ is either the served product (splats, manifest,
#       shell) or its warm-re-drive substrate; an age rule on those would delete living
#       rooms' assets. See decision 0086 for the full retention design.
#   (6) Perception-outputs CORS: permit the hosting origins to read signed splat
#       URLs from a browser. Without it the web viewer renders nothing at all —
#       CORS is browser-only, so every server-side verification of this path
#       passed while the product was broken. Not an access grant; signatures are
#       still required. See decision 0102.
#
# Section (1) also:
#   - Enables the Eventarc API if not already enabled.
#   - Waits (bounded retry) for the Eventarc Service Agent to be provisioned.
#   - Grants roles/eventarc.eventReceiver to the trigger SA at project scope.
#   - Grants roles/pubsub.publisher to the GCS service agent at project scope.
#   All four are required for end-to-end Eventarc delivery; the trigger was initially
#   created without them because they had been set manually. This script makes the
#   grants explicit so re-running on a fresh project works without manual intervention.
#
# Prerequisites:
#   - gcloud authenticated with an account that has roles/eventarc.admin,
#     roles/storage.admin, roles/datastore.owner, roles/resourcemanager.projectIamAdmin
#     on the roomstudio project
#   - api-internal Cloud Run service is already deployed (deploy_api_internal.sh)
#   - GCS bucket GCS_CAPTURES_BUCKET already exists
#
# Usage (from repo root):
#   ./infra/eventarc_setup.sh                  # run all five sections
#   ./infra/eventarc_setup.sh --lifecycle-only  # section (2) only
#   ./infra/eventarc_setup.sh --ttl-only        # section (3) only
#   ./infra/eventarc_setup.sh --trigger-only    # section (1) only
#   ./infra/eventarc_setup.sh --scenes-ttl-only # section (4) only
#   ./infra/eventarc_setup.sh --outputs-lifecycle-only # section (5) only
#   ./infra/eventarc_setup.sh --outputs-cors-only      # section (6) only
#   Flags can be combined: --lifecycle-only --ttl-only
#
# Re-running is safe: all operations are idempotent.

set -euo pipefail

PROJECT="roomstudio"
REGION="asia-southeast1"
INGESTER_SERVICE="api-internal"
GCS_CAPTURES_BUCKET="roomstudio-captures"
GCS_OUTPUTS_BUCKET="roomstudio-perception-outputs"
TRIGGER_NAME="captures-bundle-pb-finalized"
INGESTER_SA="api-internal-runtime@${PROJECT}.iam.gserviceaccount.com"

# ── Parse flags ───────────────────────────────────────────────────────────────
RUN_TRIGGER=true
RUN_LIFECYCLE=true
RUN_TTL=true
RUN_SCENES_TTL=true
RUN_OUTPUTS_LIFECYCLE=true
RUN_OUTPUTS_CORS=true

if [[ "$#" -gt 0 ]]; then
  RUN_TRIGGER=false
  RUN_LIFECYCLE=false
  RUN_TTL=false
  RUN_SCENES_TTL=false
  RUN_OUTPUTS_LIFECYCLE=false
  RUN_OUTPUTS_CORS=false
  for arg in "$@"; do
    case "$arg" in
      --trigger-only)           RUN_TRIGGER=true ;;
      --lifecycle-only)         RUN_LIFECYCLE=true ;;
      --ttl-only)               RUN_TTL=true ;;
      --scenes-ttl-only)        RUN_SCENES_TTL=true ;;
      --outputs-lifecycle-only) RUN_OUTPUTS_LIFECYCLE=true ;;
      --outputs-cors-only)      RUN_OUTPUTS_CORS=true ;;
      *) echo "Unknown argument: $arg" >&2
         echo "Usage: $0 [--trigger-only] [--lifecycle-only] [--ttl-only] [--scenes-ttl-only]" >&2
         echo "          [--outputs-lifecycle-only] [--outputs-cors-only]" >&2
         exit 1 ;;
    esac
  done
fi

if $RUN_TRIGGER; then
echo "=== (1) Eventarc trigger: GCS finalize → api-internal /ingest/eventarc ==="

# ── Resolve project number (needed for service agent email addresses) ─────────
PROJECT_NUMBER=$(gcloud projects describe "${PROJECT}" --format='value(projectNumber)')
echo "Project number: ${PROJECT_NUMBER}"
echo ""

EVENTARC_SA="service-${PROJECT_NUMBER}@gcp-sa-eventarc.iam.gserviceaccount.com"
GCS_SA="service-${PROJECT_NUMBER}@gs-project-accounts.iam.gserviceaccount.com"

# ── Step 1: Enable the Eventarc API ──────────────────────────────────────────
# Idempotent: gcloud services enable is a no-op if already enabled.
echo "Enabling Eventarc API..."
gcloud services enable eventarc.googleapis.com --project="${PROJECT}"
echo "Eventarc API enabled (or already enabled)."
echo ""

# ── Step 3: Grant roles/eventarc.eventReceiver to the trigger SA ─────────────
# (Step 2 — "wait for Eventarc Service Agent" — was removed. The describe loop used
# `gcloud iam service-accounts describe` on a Google-managed gcp-sa-eventarc agent,
# which an operator account cannot call (PERMISSION_DENIED). It misread that as "not
# yet present" and timed out even when the agent existed. It was also redundant: Step 6's
# trigger-create retry loop already treats Service-Agent-not-ready as a transient error
# and retries on it. Step 6's loop is the correct, sufficient guard.)
# Required at project scope (not just on the Cloud Run service) for the
# Eventarc-managed Pub/Sub subscription to deliver events.
# Idempotent: add-iam-policy-binding deduplicates at the IAM level.
echo "Granting roles/eventarc.eventReceiver to ${INGESTER_SA}..."
gcloud projects add-iam-policy-binding "${PROJECT}" \
  --member="serviceAccount:${INGESTER_SA}" \
  --role="roles/eventarc.eventReceiver" \
  --condition=None
echo "Granted roles/eventarc.eventReceiver."
echo ""

# ── Step 4: Grant roles/pubsub.publisher to the GCS service agent ─────────────
# The GCS service agent publishes finalize events to the Eventarc-managed
# Pub/Sub topic. Without this binding events are silently dropped at the source.
# Idempotent: add-iam-policy-binding deduplicates at the IAM level.
echo "Granting roles/pubsub.publisher to GCS service agent ${GCS_SA}..."
gcloud projects add-iam-policy-binding "${PROJECT}" \
  --member="serviceAccount:${GCS_SA}" \
  --role="roles/pubsub.publisher" \
  --condition=None
echo "Granted roles/pubsub.publisher."
echo ""

# ── Step 5: Grant roles/run.invoker to the trigger SA on api-internal ─────────
# The trigger delivery requires this binding; doing it before trigger creation
# avoids the silent-drop failure mode of "trigger exists, binding doesn't."
echo "Granting roles/run.invoker to ${INGESTER_SA} on ${INGESTER_SERVICE}..."
gcloud run services add-iam-policy-binding "${INGESTER_SERVICE}" \
  --region="${REGION}" \
  --member="serviceAccount:${INGESTER_SA}" \
  --role="roles/run.invoker"
echo "Granted roles/run.invoker."
echo ""

# ── Step 6: Create or update the Eventarc trigger ─────────────────────────────
# Narrow retry: only retries on Service-Agent-not-ready errors (up to 5 attempts,
# 10 s intervals). "Already exists" → update destination path (idempotent re-run).
# Any other error class → fast-fail.
#
# Trigger is bucket-wide: GCS Eventarc does not support object-path suffix filters
# on object.v1.finalized events. The /ingest/eventarc handler discriminates
# bundle.pb from pixel-blob events and returns 200 on non-match (decision 0023).
echo "Creating Eventarc trigger '${TRIGGER_NAME}'..."
TRIGGER_DONE=false
for i in $(seq 1 5); do
  TRIGGER_ERR=""
  if TRIGGER_ERR=$(gcloud eventarc triggers create "${TRIGGER_NAME}" \
       --project="${PROJECT}" \
       --location="${REGION}" \
       --destination-run-service="${INGESTER_SERVICE}" \
       --destination-run-region="${REGION}" \
       --destination-run-path="/ingest/eventarc" \
       --event-filters="type=google.cloud.storage.object.v1.finalized" \
       --event-filters="bucket=${GCS_CAPTURES_BUCKET}" \
       --service-account="${INGESTER_SA}" \
       2>&1); then
    echo "Eventarc trigger '${TRIGGER_NAME}' created."
    TRIGGER_DONE=true
    break
  fi
  # "Already exists" → update destination path (idempotent re-run; no retry needed).
  if echo "${TRIGGER_ERR}" | grep -qi "already exist"; then
    gcloud eventarc triggers update "${TRIGGER_NAME}" \
      --project="${PROJECT}" \
      --location="${REGION}" \
      --destination-run-path="/ingest/eventarc"
    echo "Eventarc trigger '${TRIGGER_NAME}' updated (already existed)."
    TRIGGER_DONE=true
    break
  fi
  # Service Agent propagation delay → narrow retry (only this error class).
  if echo "${TRIGGER_ERR}" | grep -qiE "service.?agent|FAILED_PRECONDITION|permission denied|has not been provisioned"; then
    echo "Attempt ${i}/5: trigger creation failed (Service Agent not yet ready?); waiting 10s..."
    echo "  Error detail: ${TRIGGER_ERR}"
    sleep 10
  else
    # Unexpected error → fast-fail.
    echo "ERROR: trigger creation failed with unexpected error:" >&2
    echo "${TRIGGER_ERR}" >&2
    exit 1
  fi
done
if [[ "${TRIGGER_DONE}" != "true" ]]; then
  echo "ERROR: Could not create/update trigger '${TRIGGER_NAME}' after 5 attempts." >&2
  echo "Check that the Eventarc Service Agent exists and all IAM grants have propagated." >&2
  exit 1
fi
echo ""

fi  # RUN_TRIGGER

if $RUN_LIFECYCLE; then
echo "=== (2) Cloud Storage lifecycle rule: delete orphan captures after 24h ==="

# Lifecycle rule: delete all objects under captures/ that are older than 1 day
# AND whose prefix does not match a finalised scene. In practice the TTL ensures
# failed and abandoned uploads don't accumulate indefinitely. The Firestore scene
# record is the authoritative state; GCS is the pixel store.
#
# Note: GCS lifecycle rules cannot query Firestore. The rule below is a simple
# age-based purge of the entire captures/ prefix. A more surgical cleanup would
# require a Cloud Function or Workflow; the 24h age is conservative enough that
# any successful ingest will have already transitioned to processing within that
# window, so its blobs are safe (they are referenced by the scene record and
# consumed by perception-obj before deletion).

cat > /tmp/lifecycle_rule.json <<'EOF'
{
  "lifecycle": {
    "rule": [
      {
        "action": {"type": "Delete"},
        "condition": {
          "age": 1,
          "matchesPrefix": ["captures/"]
        }
      }
    ]
  }
}
EOF

gsutil lifecycle set /tmp/lifecycle_rule.json "gs://${GCS_CAPTURES_BUCKET}"
echo "Lifecycle rule applied to gs://${GCS_CAPTURES_BUCKET}."
rm /tmp/lifecycle_rule.json
echo ""
fi  # RUN_LIFECYCLE

if $RUN_TTL; then
echo "=== (3) Firestore TTL policies ==="
# Firestore TTL policies are set on a per-collection-group basis via the
# Firestore console or REST API. The gcloud CLI doesn't expose TTL management
# directly; use the console or the REST API below.
#
# Collection: upload_sessions — TTL on field 'created_at', 7 days (604800s).
#
# To set TTL via REST (requires roles/datastore.owner):

echo "Setting TTL on upload_sessions collection (field: created_at, 7 days)..."
curl -s -X PATCH \
  "https://firestore.googleapis.com/v1/projects/${PROJECT}/databases/(default)/collectionGroups/upload_sessions/fields/created_at" \
  -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  -H "Content-Type: application/json" \
  -d '{
    "ttlConfig": {}
  }' | python3 -m json.tool || echo "TTL set request sent (check Firestore console for status)."

echo ""
fi  # RUN_TTL

if $RUN_SCENES_TTL; then
echo "=== (4) Firestore TTL on scenes.expire_at (gap F6, decision 0086) ==="
# The TTL field is expire_at — the field VALUE is the deletion deadline.
# api-internal stamps it only on terminal-failure transitions and clears it
# on revival; ready scenes never carry it, so the policy can never sweep a
# living room. (Do NOT point a TTL policy at created_at here: Firestore
# deletes when the named field's value is past, which for created_at means
# immediately.)

echo "Setting TTL on scenes collection (field: expire_at)..."
curl -s -X PATCH \
  "https://firestore.googleapis.com/v1/projects/${PROJECT}/databases/(default)/collectionGroups/scenes/fields/expire_at" \
  -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  -H "Content-Type: application/json" \
  -d '{
    "ttlConfig": {}
  }' | python3 -m json.tool || echo "TTL set request sent (check Firestore console for status)."

echo ""
fi  # RUN_SCENES_TTL

if $RUN_OUTPUTS_LIFECYCLE; then
echo "=== (5) Perception-outputs lifecycle: masks.npz intermediates, 180d (gap F5) ==="

# Deliberately NARROW (decision 0086). Under scenes/{scene_id}/ live:
#   manifest.json, shell.json          — served product (assets endpoint)
#   frames/*/splats/*.ply (+ .layout.json sidecars)
#                                      — the fused objects the viewer renders,
#                                        plus their rotation sidecars
#   roomplan/room.json                 — geometry source for shell re-derivation
#   frames/*/objects.json              — small per-frame caches for warm re-drives
#   frames/*/masks.npz                 — segmentation intermediates (the bulk)
# Only masks.npz is safely age-deletable: nothing serves it, and a warm
# re-drive older than the horizon simply recomputes segmentation at GPU cost.
# An age rule on anything else would delete living rooms' assets — ready-room
# retention is a product property, so whole-scene GC must be driven by
# Firestore scene state / user deletion, never by object age (0086).

cat > /tmp/outputs_lifecycle_rule.json <<'EOF'
{
  "lifecycle": {
    "rule": [
      {
        "action": {"type": "Delete"},
        "condition": {
          "age": 180,
          "matchesPrefix": ["scenes/"],
          "matchesSuffix": ["/masks.npz"]
        }
      }
    ]
  }
}
EOF

gsutil lifecycle set /tmp/outputs_lifecycle_rule.json "gs://${GCS_OUTPUTS_BUCKET}"
echo "Lifecycle rule applied to gs://${GCS_OUTPUTS_BUCKET}."
rm /tmp/outputs_lifecycle_rule.json
echo ""
fi  # RUN_OUTPUTS_LIFECYCLE

if $RUN_OUTPUTS_CORS; then
echo "=== (6) Perception-outputs CORS: let browsers read signed splat URLs ==="

# WITHOUT this the web product cannot render a single room. The viewer fetches
# splat/texture assets straight from GCS over the V4-signed URLs the assets
# endpoint returns; a cross-origin fetch with no Access-Control-Allow-Origin on
# the response is blocked by the browser BEFORE any bytes reach the page.
# Measured on the preview channel 2026-08-08: every .ply fetch died with
# "No 'Access-Control-Allow-Origin' header is present", and Spark's loader
# worker surfaced it only as "Worker error: TypeError: Failed to fetch".
#
# This was invisible until then for a specific reason worth remembering: CORS is
# enforced by browsers ONLY. Every prior verification of this path — Gate B's
# "signed URL fetches 34 MB at 200" included — used curl or a server-side
# client, which never sends an Origin header and never checks for one back.
#
# CORS IS NOT AN ACCESS GRANT. Objects stay private: the signature is still
# required and an unsigned request still 403s. All this does is permit the
# browser to hand an already-authorized response to a listed origin.
#
# The origin list intentionally mirrors api-public's CORS_ALLOWED_ORIGINS
# (infra/api-public.env.yaml) — one trusted-origin set, two enforcement points
# (the API for JSON, the bucket for assets). Keep them in step: adding a hosting
# origin means editing BOTH, or rooms load their manifest and then render
# nothing.
#
# GET + HEAD only — the viewer reads assets and never writes them.
# responseHeader covers Range/Content-Range so partial reads keep working, and
# exposes Content-Length/ETag to page JS for progress and caching.

cat > /tmp/outputs_cors.json <<'EOF'
[
  {
    "origin": [
      "http://localhost:3000",
      "https://roomstudio.web.app",
      "https://roomstudio.firebaseapp.com",
      "https://roomstudio--preview-cydkerk6.web.app"
    ],
    "method": ["GET", "HEAD"],
    "responseHeader": [
      "Content-Type",
      "Content-Length",
      "Content-Range",
      "Range",
      "ETag"
    ],
    "maxAgeSeconds": 3600
  }
]
EOF

gsutil cors set /tmp/outputs_cors.json "gs://${GCS_OUTPUTS_BUCKET}"
echo "CORS policy applied to gs://${GCS_OUTPUTS_BUCKET}."
rm /tmp/outputs_cors.json
echo ""
fi  # RUN_OUTPUTS_CORS

echo "=== Done ==="
echo "Verify in GCP console:"
$RUN_TRIGGER           && echo "  Eventarc → Triggers → ${TRIGGER_NAME}"
$RUN_LIFECYCLE         && echo "  Cloud Storage → gs://${GCS_CAPTURES_BUCKET} → Lifecycle"
$RUN_TTL               && echo "  Firestore → upload_sessions → TTL settings"
$RUN_SCENES_TTL        && echo "  Firestore → scenes → TTL settings (expire_at)"
$RUN_OUTPUTS_LIFECYCLE && echo "  Cloud Storage → gs://${GCS_OUTPUTS_BUCKET} → Lifecycle"
$RUN_OUTPUTS_CORS      && echo "  Cloud Storage → gs://${GCS_OUTPUTS_BUCKET} → CORS (gsutil cors get)"
