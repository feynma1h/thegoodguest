#!/usr/bin/env bash
# Deploy the roomstudio internal API (services/api-internal/) to Cloud Run.
#
# This service runs --no-allow-unauthenticated. Cloud Run IAM validates the
# Eventarc service account's OIDC token at the platform boundary. No in-app
# caller verification is needed or implemented in this service.
#
# Run from the repo root:
#   ./infra/deploy_api_internal.sh
#
# The script is fully idempotent. Run it before deploy_api_public.sh on the
# first deploy — it creates shared infrastructure (Firestore, GCS bucket,
# Cloud Tasks queue) that both services depend on.
#
# Prerequisites:
#   - gcloud authenticated and project set to "roomstudio"

set -euo pipefail

# ── Config ───────────────────────────────────────────────────────────────────

PROJECT_ID="roomstudio"
REGION="asia-southeast1"
SERVICE_NAME="api-internal"
REPO="roomstudio"
IMAGE_TAG="$(date +%Y%m%d-%H%M%S)"
IMAGE_URI="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/${SERVICE_NAME}:${IMAGE_TAG}"

RUNTIME_SA_NAME="api-internal-runtime"
RUNTIME_SA="${RUNTIME_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

# tasks-invoker is the SA whose identity is stamped on Cloud Tasks OIDC tokens
# so that perception-obj can verify the caller is Cloud Tasks, not the internet.
INVOKER_SA_NAME="tasks-invoker"
INVOKER_SA="${INVOKER_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

TASKS_QUEUE="perception-dispatch"
TASKS_LOCATION="${REGION}"

BUNDLE_BUCKET="roomstudio-captures"

PERCEPTION_OBJ_SERVICE="perception-obj"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

echo "=== roomstudio api-internal deploy ==="
echo "Project:  ${PROJECT_ID}"
echo "Region:   ${REGION}"
echo "Image:    ${IMAGE_URI}"
echo ""

# ── Step 1: Enable required APIs ─────────────────────────────────────────────
echo "=== 1/10: Enabling GCP APIs (idempotent) ==="
gcloud services enable \
    run.googleapis.com \
    cloudbuild.googleapis.com \
    artifactregistry.googleapis.com \
    firestore.googleapis.com \
    cloudtasks.googleapis.com \
    storage.googleapis.com \
    iam.googleapis.com \
    iamcredentials.googleapis.com \
    --project="${PROJECT_ID}"
echo "APIs enabled."

# ── Step 2: Create service accounts ──────────────────────────────────────────
echo ""
echo "=== 2/10: Service accounts ==="

_ensure_sa() {
    local sa_name="$1"
    local sa_email="$2"
    local display_name="$3"
    if gcloud iam service-accounts describe "${sa_email}" \
            --project="${PROJECT_ID}" >/dev/null 2>&1; then
        echo "  SA exists: ${sa_email}"
    else
        echo "  Creating SA: ${sa_email}"
        gcloud iam service-accounts create "${sa_name}" \
            --display-name="${display_name}" \
            --project="${PROJECT_ID}"
    fi
}

_ensure_sa "${RUNTIME_SA_NAME}" "${RUNTIME_SA}" "roomstudio API internal runtime"
_ensure_sa "${INVOKER_SA_NAME}" "${INVOKER_SA}" "Cloud Tasks OIDC invoker for perception-obj"

# ── Step 3: Bind IAM roles ────────────────────────────────────────────────────
echo ""
echo "=== 3/10: Binding IAM roles (idempotent) ==="

# api-internal-runtime: Firestore read/write for scene records and upload_sessions.
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${RUNTIME_SA}" \
    --role="roles/datastore.user" \
    --condition=None \
    --quiet

# api-internal-runtime: enqueue Cloud Tasks.
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${RUNTIME_SA}" \
    --role="roles/cloudtasks.enqueuer" \
    --condition=None \
    --quiet

# api-internal-runtime: read bundle objects from the captures bucket.
gcloud storage buckets add-iam-policy-binding "gs://${BUNDLE_BUCKET}" \
    --member="serviceAccount:${RUNTIME_SA}" \
    --role="roles/storage.objectViewer" \
    --project="${PROJECT_ID}" 2>/dev/null || {
    echo "  Note: bucket ${BUNDLE_BUCKET} may not exist yet — binding re-applied in step 7."
}

# api-internal-runtime: must be able to act as the invoker SA so Cloud Tasks
# can mint OIDC tokens stamped with tasks-invoker's identity.
gcloud iam service-accounts add-iam-policy-binding "${INVOKER_SA}" \
    --member="serviceAccount:${RUNTIME_SA}" \
    --role="roles/iam.serviceAccountUser" \
    --project="${PROJECT_ID}" \
    --quiet

# tasks-invoker: invoke the perception-obj Cloud Run service.
if gcloud run services describe "${PERCEPTION_OBJ_SERVICE}" \
        --region="${REGION}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
    gcloud run services add-iam-policy-binding "${PERCEPTION_OBJ_SERVICE}" \
        --region="${REGION}" \
        --project="${PROJECT_ID}" \
        --member="serviceAccount:${INVOKER_SA}" \
        --role="roles/run.invoker"
    echo "  tasks-invoker bound to roles/run.invoker on ${PERCEPTION_OBJ_SERVICE}."
else
    echo "  WARNING: ${PERCEPTION_OBJ_SERVICE} not found in ${REGION}."
    echo "  Skipping roles/run.invoker binding — re-run after perception-obj is deployed."
fi

# Cloud Build SA needs to be able to deploy as the runtime SA.
PROJECT_NUMBER="$(gcloud projects describe "${PROJECT_ID}" \
    --format='value(projectNumber)')"
CLOUDBUILD_SA="${PROJECT_NUMBER}@cloudbuild.gserviceaccount.com"
gcloud iam service-accounts add-iam-policy-binding "${RUNTIME_SA}" \
    --member="serviceAccount:${CLOUDBUILD_SA}" \
    --role="roles/iam.serviceAccountUser" \
    --project="${PROJECT_ID}" \
    --quiet
echo "  Cloud Build SA granted serviceAccountUser on api-internal-runtime."

# ── Step 4: Create Cloud Tasks queue ─────────────────────────────────────────
echo ""
echo "=== 4/10: Cloud Tasks queue ==="
if gcloud tasks queues describe "${TASKS_QUEUE}" \
        --location="${TASKS_LOCATION}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
    echo "  Queue exists: ${TASKS_QUEUE}"
else
    echo "  Creating queue: ${TASKS_QUEUE}"
    gcloud tasks queues create "${TASKS_QUEUE}" \
        --location="${TASKS_LOCATION}" \
        --project="${PROJECT_ID}" \
        --max-attempts=3 \
        --min-backoff=30s \
        --max-backoff=300s \
        --max-doublings=3
    echo "  Queue created."
fi

# ── Step 5: Create Firestore database ────────────────────────────────────────
echo ""
echo "=== 5/10: Firestore database ==="
if gcloud firestore databases describe --project="${PROJECT_ID}" >/dev/null 2>&1; then
    echo "  Firestore database (default) exists."
else
    echo "  Creating Firestore database (default) in ${REGION}..."
    gcloud firestore databases create \
        --location="${REGION}" \
        --project="${PROJECT_ID}"
    echo "  Firestore database created."
fi

# ── Step 6: Create bundle bucket ─────────────────────────────────────────────
echo ""
echo "=== 6/10: Bundle GCS bucket ==="
if gcloud storage buckets describe "gs://${BUNDLE_BUCKET}" \
        --project="${PROJECT_ID}" >/dev/null 2>&1; then
    echo "  Bucket exists: ${BUNDLE_BUCKET}"
else
    echo "  Creating bucket: ${BUNDLE_BUCKET}"
    gcloud storage buckets create "gs://${BUNDLE_BUCKET}" \
        --location="${REGION}" \
        --project="${PROJECT_ID}" \
        --uniform-bucket-level-access \
        --no-public-access-prevention
    echo "  Bucket created."
fi

# Re-bind storage.objectViewer now that the bucket definitely exists.
gcloud storage buckets add-iam-policy-binding "gs://${BUNDLE_BUCKET}" \
    --member="serviceAccount:${RUNTIME_SA}" \
    --role="roles/storage.objectViewer" \
    --project="${PROJECT_ID}"
echo "  api-internal-runtime granted storage.objectViewer on gs://${BUNDLE_BUCKET}."

# ── Step 7: Ensure Artifact Registry repo exists ──────────────────────────────
echo ""
echo "=== 7/10: Artifact Registry ==="
gcloud artifacts repositories describe "${REPO}" \
    --location="${REGION}" --project="${PROJECT_ID}" >/dev/null 2>&1 \
  || gcloud artifacts repositories create "${REPO}" \
        --repository-format=docker \
        --location="${REGION}" \
        --project="${PROJECT_ID}" \
        --description="roomstudio container images"
echo "  Artifact Registry repo ready."

# ── Step 8: Build container via Cloud Build ────────────────────────────────────
echo ""
echo "=== 8/10: Building container ==="
echo "Image: ${IMAGE_URI}"
gcloud builds submit . \
    --project="${PROJECT_ID}" \
    --region="${REGION}" \
    --config="infra/cloudbuild/api-internal.yaml" \
    --substitutions="_IMAGE_URI=${IMAGE_URI}"

# ── Step 9: Deploy to Cloud Run ───────────────────────────────────────────────
echo ""
echo "=== 9/10: Deploying to Cloud Run ==="
gcloud run deploy "${SERVICE_NAME}" \
    --image="${IMAGE_URI}" \
    --region="${REGION}" \
    --project="${PROJECT_ID}" \
    --platform=managed \
    --cpu=1 \
    --memory=512Mi \
    --concurrency=80 \
    --min-instances=0 \
    --max-instances=10 \
    --timeout=30 \
    --port=8080 \
    --no-allow-unauthenticated \
    --service-account="${RUNTIME_SA}" \
    --env-vars-file="infra/api-internal.env.yaml" \
    --startup-probe=httpGet.path=/health,httpGet.port=8080,initialDelaySeconds=5,periodSeconds=5,failureThreshold=6,timeoutSeconds=3 \
    --no-traffic

# ── Step 10: Print revision URL ───────────────────────────────────────────────
echo ""
echo "=== 10/10: Done ==="
REVISION="$(gcloud run revisions list \
    --service="${SERVICE_NAME}" \
    --region="${REGION}" \
    --project="${PROJECT_ID}" \
    --format='value(name)' \
    --limit=1)"
REVISION_URL="$(gcloud run revisions describe "${REVISION}" \
    --region="${REGION}" \
    --project="${PROJECT_ID}" \
    --format='value(status.url)' 2>/dev/null || echo '(unavailable)')"
SERVICE_URL="$(gcloud run services describe "${SERVICE_NAME}" \
    --region="${REGION}" --project="${PROJECT_ID}" \
    --format='value(status.url)')"

echo ""
echo "Service URL:  ${SERVICE_URL} (no traffic yet — --no-traffic flag)"
echo "Revision URL: ${REVISION_URL}"
echo ""
echo "Smoke test the revision, then flip traffic, then create Eventarc trigger:"
echo "  curl ${REVISION_URL}/health"
echo "  gcloud run services update-traffic ${SERVICE_NAME} --to-latest \\"
echo "    --region=${REGION} --project=${PROJECT_ID}"
echo "  # then run infra/eventarc_setup.sh to create the trigger against ${REVISION_URL}"
