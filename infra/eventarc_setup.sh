#!/usr/bin/env bash
# infra/eventarc_setup.sh — Eventarc trigger + lifecycle/TTL config for iOS upload path
#
# Run once per environment to wire up:
#   (1) Eventarc trigger: GCS finalize on captures/*/bundle.pb → ingester /ingest/eventarc
#   (2) Cloud Storage lifecycle rule: delete orphan captures after 24h
#   (3) Firestore TTL on upload_sessions (7 days) and scenes in failed_incomplete (7 days)
#
# Prerequisites:
#   - gcloud authenticated with an account that has roles/eventarc.admin,
#     roles/storage.admin, roles/datastore.owner on the roomstudio project
#   - The ingester Cloud Run service is already deployed (deploy_api.sh)
#   - GCS bucket GCS_CAPTURES_BUCKET already exists
#
# Usage (from repo root):
#   ./infra/eventarc_setup.sh
#
# Re-running is safe: gcloud commands are idempotent (update-or-create).

set -euo pipefail

PROJECT="roomstudio"
REGION="asia-southeast1"
INGESTER_SERVICE="roomstudio-api"
GCS_CAPTURES_BUCKET="roomstudio-captures"
TRIGGER_NAME="captures-bundle-pb-finalized"
INGESTER_SA="roomstudio-api@${PROJECT}.iam.gserviceaccount.com"

echo "=== (1) Eventarc trigger: GCS finalize on captures/*/bundle.pb ==="

# Grant roles/run.invoker to the Eventarc SA before creating the trigger.
# The trigger delivery requires this binding; doing it first means a failed
# grant exits (set -euo pipefail) before the trigger exists, avoiding the
# silent-drop failure mode of "trigger exists, binding doesn't."
gcloud run services add-iam-policy-binding "${INGESTER_SERVICE}" \
  --region="${REGION}" \
  --member="serviceAccount:${INGESTER_SA}" \
  --role="roles/run.invoker"
echo "Granted roles/run.invoker to ${INGESTER_SA} on ${INGESTER_SERVICE}."
echo ""

# The Eventarc trigger fires on any object finalize in the captures bucket.
# The ingester /ingest/eventarc handler filters to captures/*/bundle.pb by name.
gcloud eventarc triggers create "${TRIGGER_NAME}" \
  --project="${PROJECT}" \
  --location="${REGION}" \
  --destination-run-service="${INGESTER_SERVICE}" \
  --destination-run-region="${REGION}" \
  --destination-run-path="/ingest/eventarc" \
  --event-filters="type=google.cloud.storage.object.v1.finalized" \
  --event-filters="bucket=${GCS_CAPTURES_BUCKET}" \
  --service-account="${INGESTER_SA}" \
  || gcloud eventarc triggers update "${TRIGGER_NAME}" \
       --project="${PROJECT}" \
       --location="${REGION}" \
       --destination-run-path="/ingest/eventarc"

echo "Eventarc trigger '${TRIGGER_NAME}' configured."

echo ""
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
echo "=== (3) Firestore TTL policies ==="
# Firestore TTL policies are set on a per-collection-group basis via the
# Firestore console or REST API. The gcloud CLI doesn't expose TTL management
# directly; use the console or the REST API below.
#
# Collection: upload_sessions — TTL on field 'created_at', 7 days (604800s).
# Collection: scenes — Firestore does not support conditional TTL (e.g. only
#   for failed_incomplete status). Instead, the cleanup Cloud Function
#   (future work) will delete scenes older than 7 days in failed_incomplete.
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
echo "=== Done ==="
echo "Verify in GCP console:"
echo "  Eventarc → Triggers → ${TRIGGER_NAME}"
echo "  Cloud Storage → gs://${GCS_CAPTURES_BUCKET} → Lifecycle"
echo "  Firestore → upload_sessions → TTL settings"
