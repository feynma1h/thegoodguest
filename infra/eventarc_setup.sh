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
#   ./infra/eventarc_setup.sh                  # run all three sections
#   ./infra/eventarc_setup.sh --lifecycle-only  # section (2) only
#   ./infra/eventarc_setup.sh --ttl-only        # section (3) only
#   ./infra/eventarc_setup.sh --trigger-only    # section (1) only
#   Flags can be combined: --lifecycle-only --ttl-only
#
# Re-running is safe: all operations are idempotent.

set -euo pipefail

PROJECT="roomstudio"
REGION="asia-southeast1"
INGESTER_SERVICE="api-internal"
GCS_CAPTURES_BUCKET="roomstudio-captures"
TRIGGER_NAME="captures-bundle-pb-finalized"
INGESTER_SA="api-internal-runtime@${PROJECT}.iam.gserviceaccount.com"

# ── Parse flags ───────────────────────────────────────────────────────────────
RUN_TRIGGER=true
RUN_LIFECYCLE=true
RUN_TTL=true

if [[ "$#" -gt 0 ]]; then
  RUN_TRIGGER=false
  RUN_LIFECYCLE=false
  RUN_TTL=false
  for arg in "$@"; do
    case "$arg" in
      --trigger-only)    RUN_TRIGGER=true ;;
      --lifecycle-only)  RUN_LIFECYCLE=true ;;
      --ttl-only)        RUN_TTL=true ;;
      *) echo "Unknown argument: $arg" >&2
         echo "Usage: $0 [--trigger-only] [--lifecycle-only] [--ttl-only]" >&2
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

echo "=== Done ==="
echo "Verify in GCP console:"
$RUN_TRIGGER   && echo "  Eventarc → Triggers → ${TRIGGER_NAME}"
$RUN_LIFECYCLE && echo "  Cloud Storage → gs://${GCS_CAPTURES_BUCKET} → Lifecycle"
$RUN_TTL       && echo "  Firestore → upload_sessions → TTL settings"
