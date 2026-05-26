#!/usr/bin/env bash
# Deploy the roomstudio public API (services/api-public/) to Cloud Run.
#
# This service runs --allow-unauthenticated. Firebase ID token verification
# is handled in-app by FirebaseTokenVerifier. Cloud Run IAM does NOT gate
# this service — iOS clients send Firebase JWTs, not Google OIDC tokens.
#
# Run from the repo root:
#   ./infra/deploy_api_public.sh
#
# The script is fully idempotent: safe to re-run after a failed deploy or to
# refresh IAM bindings after a change.
#
# Prerequisites:
#   - gcloud authenticated and project set to "roomstudio"
#   - See infra/deploy_api_internal.sh for steps that must run first
#     (Firestore database, GCS bucket).

set -euo pipefail

# ── Config ───────────────────────────────────────────────────────────────────

PROJECT_ID="roomstudio"
REGION="asia-southeast1"
SERVICE_NAME="api-public"
REPO="roomstudio"
IMAGE_TAG="$(date +%Y%m%d-%H%M%S)"
IMAGE_URI="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/${SERVICE_NAME}:${IMAGE_TAG}"

RUNTIME_SA_NAME="api-public-runtime"
RUNTIME_SA="${RUNTIME_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

BUNDLE_BUCKET="roomstudio-captures"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

echo "=== roomstudio api-public deploy ==="
echo "Project:  ${PROJECT_ID}"
echo "Region:   ${REGION}"
echo "Image:    ${IMAGE_URI}"
echo ""

# ── Step 1: Enable required APIs ─────────────────────────────────────────────
echo "=== 1/7: Enabling GCP APIs (idempotent) ==="
gcloud services enable \
    run.googleapis.com \
    cloudbuild.googleapis.com \
    artifactregistry.googleapis.com \
    firestore.googleapis.com \
    storage.googleapis.com \
    iam.googleapis.com \
    --project="${PROJECT_ID}"
echo "APIs enabled."

# ── Step 2: Create service account ───────────────────────────────────────────
echo ""
echo "=== 2/7: Service account ==="
if gcloud iam service-accounts describe "${RUNTIME_SA}" \
        --project="${PROJECT_ID}" >/dev/null 2>&1; then
    echo "  SA exists: ${RUNTIME_SA}"
else
    echo "  Creating SA: ${RUNTIME_SA}"
    gcloud iam service-accounts create "${RUNTIME_SA_NAME}" \
        --display-name="roomstudio API public runtime" \
        --project="${PROJECT_ID}"
fi

# ── Step 3: Bind IAM roles ────────────────────────────────────────────────────
echo ""
echo "=== 3/7: Binding IAM roles (idempotent) ==="

# api-public-runtime: Firestore read/write for upload_sessions collection.
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${RUNTIME_SA}" \
    --role="roles/datastore.user" \
    --condition=None \
    --quiet

# api-public-runtime: GCS write on captures bucket for minting resumable URIs.
# objectViewer (read-only) is not enough — gcs_mint_resumable_uri POSTs to
# initiate a resumable upload, which requires storage.objects.create.
# objectAdmin is the minimal managed role that includes create + read + delete.
gcloud storage buckets add-iam-policy-binding "gs://${BUNDLE_BUCKET}" \
    --member="serviceAccount:${RUNTIME_SA}" \
    --role="roles/storage.objectAdmin" \
    --project="${PROJECT_ID}" 2>/dev/null || {
    echo "  Note: bucket ${BUNDLE_BUCKET} may not exist yet — re-run after bucket creation."
}

# Cloud Build SA needs to be able to deploy as the runtime SA.
PROJECT_NUMBER="$(gcloud projects describe "${PROJECT_ID}" \
    --format='value(projectNumber)')"
CLOUDBUILD_SA="${PROJECT_NUMBER}@cloudbuild.gserviceaccount.com"
gcloud iam service-accounts add-iam-policy-binding "${RUNTIME_SA}" \
    --member="serviceAccount:${CLOUDBUILD_SA}" \
    --role="roles/iam.serviceAccountUser" \
    --project="${PROJECT_ID}" \
    --quiet
echo "  Cloud Build SA granted serviceAccountUser on api-public-runtime."

# ── Step 4: Ensure Artifact Registry repo exists ──────────────────────────────
echo ""
echo "=== 4/7: Artifact Registry ==="
gcloud artifacts repositories describe "${REPO}" \
    --location="${REGION}" --project="${PROJECT_ID}" >/dev/null 2>&1 \
  || gcloud artifacts repositories create "${REPO}" \
        --repository-format=docker \
        --location="${REGION}" \
        --project="${PROJECT_ID}" \
        --description="roomstudio container images"
echo "  Artifact Registry repo ready."

# ── Step 5: Build container via Cloud Build ────────────────────────────────────
echo ""
echo "=== 5/7: Building container ==="
echo "Image: ${IMAGE_URI}"
gcloud builds submit . \
    --project="${PROJECT_ID}" \
    --region="${REGION}" \
    --config="infra/cloudbuild/api-public.yaml" \
    --substitutions="_IMAGE_URI=${IMAGE_URI}"

# ── Step 6: Deploy to Cloud Run ───────────────────────────────────────────────
echo ""
echo "=== 6/7: Deploying to Cloud Run ==="
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
    --allow-unauthenticated \
    --service-account="${RUNTIME_SA}" \
    --env-vars-file="infra/api-public.env.yaml" \
    --startup-probe=httpGet.path=/health,httpGet.port=8080,initialDelaySeconds=5,periodSeconds=5,failureThreshold=6,timeoutSeconds=3 \
    --no-traffic

# ── Step 7: Print revision URL ────────────────────────────────────────────────
echo ""
echo "=== 7/7: Done ==="
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
echo "Smoke test the revision directly, then flip traffic:"
echo "  curl ${REVISION_URL}/health"
echo "  gcloud run services update-traffic ${SERVICE_NAME} --to-latest \\"
echo "    --region=${REGION} --project=${PROJECT_ID}"
